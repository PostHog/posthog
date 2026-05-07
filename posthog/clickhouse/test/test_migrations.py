import os
import re
import ast
import sys
import importlib
from collections import defaultdict
from pathlib import Path

from unittest import TestCase, mock

from infi.clickhouse_orm.utils import import_submodules

from posthog.clickhouse.client.connection import NodeRole

# Migrations created before this validation existed are grandfathered.
MIN_CHECKED_MIGRATION_NUMBER = 150
MIGRATIONS_PACKAGE_NAME = "posthog.clickhouse.migrations"
# `operations` lists can be cloud-gated; re-evaluate them under each prod-shaped value plus
# the unset default so gated branches don't silently bypass the guard.
CLOUD_DEPLOYMENTS_TO_CHECK = ("", "US", "EU", "DEV")


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
        migrations_dir = Path(__file__).parent.parent / "migrations"
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
        self, sql: str, node_roles: list[NodeRole], sharded: bool | None, is_alter_on_replicated_table: bool | None
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

        if not sharded and is_alter_on_replicated_table and set(node_roles) != {NodeRole.DATA}:
            errors.append("ALTER TABLE on non-sharded tables must have node_role=NodeRole.DATA")

        return errors

    def _check_operations(self, migration_name: str, operations, deployment_label: str, *, full: bool) -> list[dict]:
        """Walk a migration's operations and return any convention violations.

        ``full=False`` is used for per-deployment passes: it only runs the cheap, deployment-
        agnostic checks (ON CLUSTER + missing _sql) so cloud-gated branches don't get flagged
        against legacy ALTER-TABLE flag rules they already shipped past.
        """
        violations: list[dict] = []
        for idx, operation in enumerate(operations):
            sql = getattr(operation, "_sql", None)
            if sql is None:
                # Every op in a >=0150 migration is expected to go through run_sql_with_exceptions,
                # which is what attaches _sql/_node_roles/_sharded/_is_alter_on_replicated_table.
                # An op without _sql is invisible to all the per-SQL checks below — fail loud rather
                # than skip it silently the way the previous version of this test did.
                violations.append(
                    {
                        "migration": migration_name,
                        "deployment": deployment_label,
                        "operation_index": idx,
                        "table_name": "unknown",
                        "sql_preview": f"<{type(operation).__name__} without _sql>",
                        "errors": [
                            "operation is missing _sql metadata; wrap it with run_sql_with_exceptions "
                            "so the migration test suite can validate it"
                        ],
                    }
                )
                continue

            errors: list[str] = []
            if "ON CLUSTER" in sql:
                errors.append("ON CLUSTER is not supposed to be used in migrations")
            if full:
                errors += self.check_alter_table(
                    sql,
                    operation._node_roles,
                    operation._sharded,
                    operation._is_alter_on_replicated_table,
                )

            if errors:
                table_match = re.search(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([^\s(]+)", sql, re.IGNORECASE)
                violations.append(
                    {
                        "migration": migration_name,
                        "deployment": deployment_label,
                        "operation_index": idx,
                        "table_name": table_match.group(1) if table_match else "unknown",
                        "sql_preview": sql[:200] + "..." if len(sql) > 200 else sql,
                        "errors": errors,
                    }
                )
        return violations

    @staticmethod
    def _checked_modules():
        """Yield (name, module) pairs for migrations subject to the per-op convention checks."""
        for name, module in sorted(import_submodules(MIGRATIONS_PACKAGE_NAME).items()):
            if not re.match(r"^\d+_", name):
                continue
            number = int(re.match(r"^(\d+)_", name).group(1))  # type: ignore[union-attr]
            if number < MIN_CHECKED_MIGRATION_NUMBER:
                continue
            yield name, module

    def test_alter_on_replicated_tables_has_correct_flag(self):
        """Validate ALTER TABLE flagging + ON CLUSTER absence under every prod CLOUD_DEPLOYMENT.

        Some migrations build ``operations`` differently depending on
        ``settings.CLOUD_DEPLOYMENT`` (e.g. cloud-only Kafka tables). Iterating only under the
        default test value would let those gated branches bypass the guard, so we re-import each
        migration module under each deployment value and union the violations.
        """
        violations: list[dict] = []

        # Default deployment: full convention check (ON CLUSTER + ALTER flags + missing _sql).
        for name, module in self._checked_modules():
            operations = getattr(module, "operations", None)
            if operations is None:
                continue
            violations += self._check_operations(name, operations, "<default>", full=True)

        # Other prod-shaped deployments: cheap deployment-agnostic checks only. We skip the
        # ALTER flag check here because some legacy cloud-gated migrations shipped without it
        # and re-running the strict check would now fail on already-applied migrations.
        reloaded_names: set[str] = set()
        try:
            for deployment in CLOUD_DEPLOYMENTS_TO_CHECK:
                if not deployment:
                    continue
                with mock.patch("posthog.settings.CLOUD_DEPLOYMENT", deployment):
                    for name, module in self._checked_modules():
                        # Reload so the module re-evaluates its top-level `operations` list under the
                        # patched CLOUD_DEPLOYMENT — the gated branch in 0247 only materializes when
                        # the value matches one of US/EU/DEV.
                        module = importlib.reload(module)
                        reloaded_names.add(module.__name__)
                        operations = getattr(module, "operations", None)
                        if operations is None:
                            continue
                        violations += self._check_operations(name, operations, deployment, full=False)
        finally:
            # `importlib.reload` mutates the module in place, so the patched-CLOUD_DEPLOYMENT
            # version of each top-level `operations` list survives in sys.modules after the
            # mock context exits. Re-reload each touched module under the default deployment
            # so later tests in the same process see the unpatched state.
            for name in reloaded_names:
                module = sys.modules.get(name)
                if module is not None:
                    importlib.reload(module)

        if violations:
            error_message = "Found ClickHouse migration operations with convention violations:\n\n"
            for v in violations:
                error_message += f"Migration: {v['migration']} (CLOUD_DEPLOYMENT={v['deployment']})\n"
                error_message += f"  Operation index: {v['operation_index']}\n"
                error_message += f"  Table: {v['table_name']}\n"
                error_message += f"  SQL preview: {v['sql_preview']}\n"
                error_message += f"  Errors: \n\t-{'\n\t-'.join(v['errors'])}\n\n"
            error_message += "For more information, see posthog/clickhouse/migrations/AGENTS.md\n"
            self.fail(error_message)

    def test_no_on_cluster_in_migration_source_strings(self):
        """Static backstop: flag ``ON CLUSTER`` in any string literal in migration source.

        ``test_alter_on_replicated_tables_has_correct_flag`` only sees SQL that survives the
        runtime gates (``operations`` may be empty under some ``CLOUD_DEPLOYMENT`` values, an op
        may not be wrapped via ``run_sql_with_exceptions``). This test parses each migration's
        AST and inspects every string constant — catching ``ON CLUSTER`` regardless of how the
        operation is constructed or whether it's actually included at runtime.
        """
        migrations_dir = Path(__file__).parent.parent / "migrations"

        violations: list[tuple[str, int, str]] = []
        for path in sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.py")):
            number = int(path.name.split("_", 1)[0])
            if number < MIN_CHECKED_MIGRATION_NUMBER:
                continue
            try:
                tree = ast.parse(path.read_text(), filename=str(path))
            except SyntaxError as exc:
                self.fail(f"Could not parse {path.name}: {exc}")

            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if "ON CLUSTER" in node.value and not self._is_in_module_docstring(tree, node):
                        violations.append((path.name, node.lineno, node.value.strip()[:160]))

        if violations:
            msg = "Found `ON CLUSTER` in migration source string literals:\n\n"
            for name, line, snippet in violations:
                msg += f"  {name}:{line}: {snippet}\n"
            msg += "\nClickHouse migrations must not use `ON CLUSTER` — do not put it in new code, "
            msg += "for old SQL use ON_CLUSTER_CLAUSE(False) "
            msg += "and run via node_roles=NodeRole.X per-shard. See posthog/clickhouse/migrations/AGENTS.md.\n"
            self.fail(msg)

    @staticmethod
    def _is_in_module_docstring(tree: ast.Module, node: ast.Constant) -> bool:
        """Return True iff `node` is the module-level docstring of `tree`."""
        if not tree.body or not isinstance(tree.body[0], ast.Expr):
            return False
        first = tree.body[0].value
        return first is node
