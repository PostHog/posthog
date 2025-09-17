#!/usr/bin/env python
"""
Cached migration checker - stores hash of migration files to detect changes.
If no migrations changed, skip the expensive Django startup check.
"""

# allow print statements in this script
# ruff: noqa:T201

import os
import sys
import json
import time
import hashlib
from pathlib import Path

# Get the project root (parent of bin directory)
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CACHE_FILE = PROJECT_ROOT / ".migration_cache.json"

# Change to project root for all operations
os.chdir(PROJECT_ROOT)

# Add project root to Python path so Django can find settings
sys.path.insert(0, str(PROJECT_ROOT))


def get_migration_hash():
    """Calculate hash of all migration files"""
    hasher = hashlib.sha256()
    migration_files = []

    # Find all migration files from project root
    for root, dirs, _ in os.walk(PROJECT_ROOT):
        # Skip virtual environments and node_modules
        if "venv" in root or "node_modules" in root or ".flox" in root:
            continue
        if "migrations" in dirs:
            migration_dir = os.path.join(root, "migrations")
            for file in os.listdir(migration_dir):
                if file.endswith(".py") and not file.startswith("__"):
                    filepath = os.path.join(migration_dir, file)
                    migration_files.append(filepath)
                    with open(filepath, "rb") as f:
                        hasher.update(f.read())

    return hasher.hexdigest(), len(migration_files)


def load_cache():
    """Load cached migration state"""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except:
            return None
    return None


def save_cache(data):
    """Save migration state to cache"""
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)


def check_migrations_django():
    """Full Django migration check"""
    os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
    import django

    django.setup()

    from io import StringIO

    from django.core.management import call_command

    # Check if migrations are needed
    try:
        out = StringIO()
        call_command("migrate", "--check", stdout=out, stderr=out, verbosity=0)
        return True  # All migrations applied
    except SystemExit:
        return False  # Migrations needed


# Main logic
start = time.perf_counter()

# Calculate current migration hash
current_hash, file_count = get_migration_hash()
print(f"📁 Found {file_count} migration files")

# Load cache
cache = load_cache()

if cache and cache.get("hash") == current_hash and cache.get("status") == "applied":
    elapsed = time.perf_counter() - start
    print(f"✅ Migrations unchanged since last check (verified in {elapsed:.3f}s)")
    print("   Skipping Django startup - using cached status")
    sys.exit(0)

print("🔄 Migration files changed or cache missing, performing full check...")

# Do full Django check
django_start = time.perf_counter()
migrations_ok = check_migrations_django()
django_elapsed = time.perf_counter() - django_start

# Save cache
save_cache(
    {
        "hash": current_hash,
        "status": "applied" if migrations_ok else "pending",
        "file_count": file_count,
        "timestamp": time.time(),
    }
)

total_elapsed = time.perf_counter() - start

if migrations_ok:
    print(f"✅ All migrations applied (checked in {total_elapsed:.2f}s, Django: {django_elapsed:.2f}s)")
    sys.exit(0)
else:
    print(f"❌ Migrations needed (checked in {total_elapsed:.2f}s)")
    sys.exit(1)
