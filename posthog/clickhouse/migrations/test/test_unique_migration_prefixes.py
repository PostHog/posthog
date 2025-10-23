import os
import re
from collections import defaultdict
from pathlib import Path

from unittest import TestCase


class TestUniqueMigrationPrefixes(TestCase):
    def test_migration_prefixes_are_unique(self):
        """Test that no two migration files have the same numeric prefix."""
        migrations_dir = Path(__file__).parent.parent
        migration_files = [f for f in os.listdir(migrations_dir) if f.endswith(".py") and f != "__init__.py"]

        # Extract prefixes and group by prefix
        prefix_to_files = defaultdict(list)

        for migration_file in migration_files:
            match = re.match(r"^(\d+)_(.+)\.py$", migration_file)
            if match:
                prefix = match.group(1)
                # Skip files with prefix less than 0083
                if int(prefix) <= 83:
                    continue
                prefix_to_files[prefix].append(migration_file)

        # Find duplicates
        duplicates = {prefix: files for prefix, files in prefix_to_files.items() if len(files) > 1}

        if duplicates:
            error_message = "Found migration files with duplicate prefixes:\n"
            for prefix, files in duplicates.items():
                error_message += f"  Prefix {prefix}:\n"
                for file in files:
                    error_message += f"    - {file}\n"
            error_message += "\nEach migration must have a unique numeric prefix to ensure proper ordering."

            self.fail(error_message)

    def test_max_migration_txt_is_valid(self):
        """Test that max_migration.txt exists and points to the latest migration."""
        migrations_dir = Path(__file__).parent.parent
        max_migration_txt = migrations_dir / "max_migration.txt"

        # Check that max_migration.txt exists
        self.assertTrue(
            max_migration_txt.exists(),
            "max_migration.txt does not exist in clickhouse/migrations/. "
            "This file is required to prevent migration conflicts.",
        )

        # Read the max_migration.txt file
        max_migration_content = max_migration_txt.read_text().strip()
        lines = max_migration_content.splitlines()

        # Check that it contains exactly one line
        self.assertEqual(
            len(lines),
            1,
            f"max_migration.txt contains {len(lines)} lines but should contain exactly 1. "
            "This may be the result of a git merge. Fix the file to contain only the name "
            "of the latest migration.",
        )

        max_migration_name = lines[0]

        # Check that the migration file exists
        max_migration_file = migrations_dir / f"{max_migration_name}.py"
        self.assertTrue(
            max_migration_file.exists(),
            f"max_migration.txt points to {max_migration_name!r} but that file doesn't exist. "
            "Update max_migration.txt to point to the latest migration.",
        )

        # Get all migration files
        migration_files = [
            f[:-3]  # Remove .py extension
            for f in os.listdir(migrations_dir)
            if f.endswith(".py") and f != "__init__.py" and re.match(r"^\d+_", f)
        ]

        # Find the actual latest migration by numeric prefix
        latest_migration = max(
            migration_files,
            key=lambda f: int(re.match(r"^(\d+)_", f).group(1)),  # type: ignore
        )

        # Check that max_migration.txt points to the latest migration
        self.assertEqual(
            max_migration_name,
            latest_migration,
            f"max_migration.txt contains {max_migration_name!r} but the latest migration "
            f"is {latest_migration!r}. Update max_migration.txt to contain {latest_migration!r}.",
        )
