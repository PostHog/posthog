# Auto-import all migrations to ensure they are registered
import logging
import importlib
from pathlib import Path

# Get the current directory (migrations folder)
current_dir = Path(__file__).parent

# Find all Python files that start with underscore and numbers (migration files)
migration_files = []
for file_path in current_dir.glob("_*.py"):
    if file_path.name != "__init__.py":
        migration_files.append(file_path.stem)  # Get filename without extension

# Sort migration files to ensure consistent import order
migration_files.sort()

# Import all migration files
for migration_file in migration_files:
    try:
        importlib.import_module(f".{migration_file}", package=__package__)
    except ImportError as e:
        # Log but don't fail
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to import migration {migration_file}: {e}")
