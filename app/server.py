import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from alignment import perform_alignment, tokenize_code

app = Flask(__name__)
app.secret_key = "23"

# Configure SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Database model for user
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

# Database model for alignment history
class AlignmentHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    file1_name = db.Column(db.String(120), nullable=False)
    file2_name = db.Column(db.String(120), nullable=False)
    file1_content = db.Column(db.Text, nullable=False)  # Content of File 1
    file2_content = db.Column(db.Text, nullable=False)  # Content of File 2
    aligned_file1 = db.Column(db.Text, nullable=False)  # Aligned content of File 1
    aligned_file2 = db.Column(db.Text, nullable=False)  # Aligned content of File 2
    similarity = db.Column(db.Float, nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    alignment_id = db.Column(db.String(36), unique=True, nullable=False)


with app.app_context():
    db.create_all()

def current_user():
    """Retrieve the currently logged-in user."""
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

def manage_alignment_storage(user_id):
    """Ensure only the last 5 alignments have files saved on disk."""
    alignments = AlignmentHistory.query.filter_by(user_id=user_id).order_by(AlignmentHistory.date_created).all()
    if len(alignments) > 5:
        for alignment in alignments[:-5]:  # Keep only the last 5 alignments
            alignment_dir = os.path.join("uploads", str(user_id), alignment.alignment_id)
            if os.path.exists(alignment_dir):
                for file in os.listdir(alignment_dir):
                    os.remove(os.path.join(alignment_dir, file))
                os.rmdir(alignment_dir)

@app.route('/')
def index():
    """Landing page."""
    if current_user():
        return redirect(url_for('home'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Register a new user."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if User.query.filter_by(username=username).first():
            flash("Username already exists. Please choose another one.", "error")
            return render_template('register.html')

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        session['user_id'] = new_user.id
        return redirect(url_for('home'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Log in a user."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return redirect(url_for('home'))
        else:
            flash("Invalid username or password.", "error")
            return render_template('login.html')

    return render_template('login.html')

@app.route('/logout')
def logout():
    """Log out the current user."""
    session.pop('user_id', None)
    return redirect(url_for('index'))

@app.route('/home')
def home():
    """Home page for logged-in users."""
    if not current_user():
        return redirect(url_for('login'))
    return render_template('based/home.html', current_user=current_user())

@app.route('/tools/pairwise', methods=['GET', 'POST'])
def align():
    """
    Handle pairwise alignment for Python files. Save results to the database.
    """
    if not current_user():
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Retrieve uploaded files
        file1 = request.files.get('file1')
        file2 = request.files.get('file2')

        # Initialize an error list
        errors = []

        # Validate file uploads
        if not file1 or not file2:
            errors.append("Both files are required.")
        if file1 and not file1.filename.endswith('.py'):
            errors.append("File 1 must be a Python file with a .py extension.")
        if file2 and not file2.filename.endswith('.py'):
            errors.append("File 2 must be a Python file with a .py extension.")

        # Validate file sizes
        max_size = 1 * 1024 * 1024  # 1MB in bytes
        if file1 and file1.content_length > max_size:
            errors.append("File 1 must be smaller than 1MB.")
        if file2 and file2.content_length > max_size:
            errors.append("File 2 must be smaller than 1MB.")

        # Handle errors
        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(url_for('align'))

        # Read file content
        file1_content = file1.read().decode('utf-8', errors='replace').strip()
        file2_content = file2.read().decode('utf-8', errors='replace').strip()

        # Perform alignment
        alignment_result = perform_alignment(file1_content, file2_content)

        # Save results to the database
        alignment = AlignmentHistory(
            user_id=session['user_id'],
            file1_name=file1.filename,
            file2_name=file2.filename,
            file1_content=file1_content,
            file2_content=file2_content,
            aligned_file1=alignment_result['aligned_file1'],
            aligned_file2=alignment_result['aligned_file2'],
            similarity=alignment_result['similarity'],  # Save similarity score
            alignment_id=str(uuid.uuid4())
        )
        db.session.add(alignment)
        db.session.commit()

        flash("Alignment successfully performed!", "success")
        return redirect(url_for('alignment_results', alignment_id=alignment.alignment_id))

    return render_template('based/align.html')

@app.route('/results/p/<alignment_id>')
def alignment_results(alignment_id):
    """
    Display the results of a specific alignment.
    """
    if not current_user():
        return redirect(url_for('login'))

    alignment = AlignmentHistory.query.filter_by(
        alignment_id=alignment_id, user_id=session['user_id']
    ).first()

    if not alignment:
        flash("Result not found or access denied.", "error")
        return redirect(url_for('history'))

    # Render results with alignment data from the database
    return render_template(
        'based/results.html',
        similarity=alignment.similarity,
        file1=alignment.file1_content,
        file2=alignment.file2_content,
        file1_tokens=alignment.aligned_file1.split("\n"),  # Split tokens by lines
        file2_tokens=alignment.aligned_file2.split("\n"),  # Split tokens by lines
        file1_name=alignment.file1_name,
        file2_name=alignment.file2_name
    )

@app.route('/history')
def history():
    """
    View user's alignment history.
    """
    if not current_user():
        return redirect(url_for('login'))

    alignments = AlignmentHistory.query.filter_by(user_id=session['user_id']).order_by(
        AlignmentHistory.date_created.desc()
    ).all()

    return render_template('based/history.html', alignments=alignments)

@app.route('/about')
def about():
    """About page."""
    if not current_user():
        return redirect(url_for('login'))
    return render_template('based/about.html')

if __name__ == '__main__':
    app.run(debug=True)
