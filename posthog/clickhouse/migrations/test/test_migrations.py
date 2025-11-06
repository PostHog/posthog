import os
import re
from collections import defaultdict
from pathlib import Path

from unittest import TestCase

from infi.clickhouse_orm.utils import import_submodules

from posthog.clickhouse.client.connection import NodeRole


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

    def check_alter_table(
        self, sql: str, node_roles: list[NodeRole], sharded: bool, is_alter_on_replicated_table: bool
    ):
        # Check if this is an ALTER TABLE statement
        if not re.search(r"\bALTER\s+TABLE\b", sql, re.IGNORECASE):
            return []

        errors = []
        if sharded is None:
            errors.append("sharded parameter must be explicitly specified for ALTER TABLE queries")

        if is_alter_on_replicated_table is None:
            errors.append("is_alter_on_replicated_table parameter must be explicitly specified for ALTER TABLE queries")

        if sharded and node_roles != [NodeRole.DATA]:
            errors.append("ALTER TABLE on sharded tables must have node_role=NodeRole.DATA")

        if not sharded and is_alter_on_replicated_table and set(node_roles) != {NodeRole.DATA, NodeRole.COORDINATOR}:
            errors.append(
                "ALTER TABLE on non-sharded tables must have node_role=NodeRole.DATA and NodeRole.COORDINATOR"
            )

        return errors

    def test_alter_on_replicated_tables_has_correct_flag(self):
        """Test that ALTER TABLE on replicated non-sharded tables uses is_alter_on_replicated_table=True."""
        MIGRATIONS_PACKAGE_NAME = "posthog.clickhouse.migrations"

        # Load all migration modules
        modules = import_submodules(MIGRATIONS_PACKAGE_NAME)

        violations = []

        for migration_name, module in sorted(modules.items()):
            # Skip if not a numbered migration
            if not re.match(r"^\d+_", migration_name):
                continue

            # Skip migrations before 0167 (validation applies to new migrations only)
            # Migrations 0083-0166 may not follow this rule as they were created before this validation
            migration_number = int(re.match(r"^(\d+)_", migration_name).group(1))
            if migration_number < 150:
                continue

            # Get operations from the module
            if not hasattr(module, "operations"):
                continue

            operations = module.operations

            for idx, operation in enumerate(operations):
                # Check if this operation has our metadata (from run_sql_with_exceptions)
                if not hasattr(operation, "_sql"):
                    continue

                sql = operation._sql
                node_roles = operation._node_roles
                sharded = operation._sharded
                is_alter_on_replicated_table = operation._is_alter_on_replicated_table

                errors = []
                if "ON CLUSTER" in sql:
                    errors.append("ON CLUSTER is not supposed to used in migration")

                errors = errors + self.check_alter_table(sql, node_roles, sharded, is_alter_on_replicated_table)

                if errors:
                    table_match = re.search(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([^\s(]+)", sql, re.IGNORECASE)
                    table_name = table_match.group(1) if table_match else "unknown"

                    violations.append(
                        {
                            "migration": migration_name,
                            "operation_index": idx,
                            "table_name": table_name,
                            "sql_preview": sql[:200] + "..." if len(sql) > 200 else sql,
                            "errors": errors,
                        }
                    )

        if violations:
            error_message = "Found ALTER TABLE statements with some incorrect arguments:\n\n"

            for v in violations:
                error_message += f"Migration: {v['migration']}\n"
                error_message += f"  Operation index: {v['operation_index']}\n"
                error_message += f"  Table: {v['table_name']}\n"
                error_message += f"  SQL preview: {v['sql_preview']}\n"
                error_message += f"  Errors: \n\t-{'\n\t-'.join(v['errors'])}\n"
                error_message += "\n"

            error_message += "For more information, see posthog/clickhouse/migrations/AGENTS.md\n"

            self.fail(error_message)
