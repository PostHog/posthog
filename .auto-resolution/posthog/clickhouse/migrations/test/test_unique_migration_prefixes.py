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
