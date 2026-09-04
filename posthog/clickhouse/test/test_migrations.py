import os
import re
import ast
import sys
import importlib
from collections import defaultdict
from pathlib import Path

from unittest import TestCase, mock

from infi.clickhouse_orm.utils import import_submodules
from parameterized import parameterized

from posthog.clickhouse.client.connection import DATA_NODE_ROLES, NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Migrations created before this validation existed are grandfathered.
MIN_CHECKED_MIGRATION_NUMBER = 150
MIGRATIONS_PACKAGE_NAME = "posthog.clickhouse.migrations"
# `operations` lists can be cloud-gated; re-evaluate them under each prod-shaped value plus
# the unset default so gated branches don't silently bypass the guard.
CLOUD_DEPLOYMENTS_TO_CHECK = ("", "US", "EU", "DEV")
# Migrations from this number on may not run ClickHouse mutations (earlier ones are grandfathered).
MIN_MUTATION_CHECKED_MIGRATION_NUMBER = 314
# A migration that has to carry a mutation (the ClickHouse team already applied it on every cloud environment, so the
# IF EXISTS-guarded statement is a no-op there) attests to that with this module attribute.
MUTATION_ATTESTATION_ATTRIBUTE = "CLICKHOUSE_TEAM_APPLIED_MUTATION"

# ALTER commands ClickHouse executes as a mutation over every part (AlterCommand::isRequireMutationStage and the
# MutationCommand types) plus the lightweight-delete form. `MODIFY COLUMN` counts only with a type; a COMMENT, DEFAULT,
# CODEC or SETTINGS change is metadata. `MODIFY TTL` counts because materialize_ttl_after_modify queues one.
_MUTATION_COMMAND = re.compile(
    r"\b(?:"
    r"DROP\s+(?:COLUMN|INDEX|PROJECTION|STATISTICS?)"
    r"|MATERIALIZE\s+(?:COLUMN|INDEX|PROJECTION|TTL|STATISTICS?)"
    r"|CLEAR\s+(?:COLUMN|INDEX|PROJECTION|STATISTICS?)"
    r"|RENAME\s+COLUMN"
    r"|MODIFY\s+TTL"
    r"|MODIFY\s+COLUMN\s+(?:IF\s+EXISTS\s+)?\S+\s+(?!COMMENT\b|DEFAULT\b|CODEC\b|REMOVE\b|MODIFY\b|RESET\b|TTL\b|SETTINGS\b)[A-Za-z]"
    r"|APPLY\s+DELETED\s+MASK"
    r"|UPDATE\s+\S+\s*="
    r"|DELETE\s+WHERE"
    r"|DELETE\s+FROM"
    r")",
    re.IGNORECASE,
)


def mutation_command(sql: str) -> str | None:
    """The first ALTER command in `sql` that ClickHouse runs as a mutation, or None."""
    match = _MUTATION_COMMAND.search(sql)
    return match.group(0) if match else None


def mutation_error(command: str) -> str:
    return (
        f"`{command}` runs as a ClickHouse mutation that rewrites every part of the table. Migrations must not run "
        "mutations: a table with unfinished mutations (sharded_events always has deletions in flight) rejects new ones "
        "with `Too many unfinished mutations`, which blocked every deploy on 2026-09-04, and on sharded_events a "
        "mutation may never finish in prod. Have the ClickHouse team apply the change on every cloud environment "
        f'first, then set {MUTATION_ATTESTATION_ATTRIBUTE} = "<date, who, link>" in the migration so the IF EXISTS-guarded '
        "statement is a no-op there. See posthog/clickhouse/migrations/AGENTS.md."
    )


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

        allowed_roles_label = "one of " + ", ".join(
            f"NodeRole.{r.name}" for r in sorted(DATA_NODE_ROLES, key=lambda r: r.name)
        )

        if sharded and (len(node_roles) != 1 or node_roles[0] not in DATA_NODE_ROLES):
            errors.append(f"ALTER TABLE on sharded tables must have node_role={allowed_roles_label}")

        if (
            not sharded
            and is_alter_on_replicated_table
            and (len(node_roles) != 1 or node_roles[0] not in DATA_NODE_ROLES)
        ):
            errors.append(f"ALTER TABLE on non-sharded tables must have node_role={allowed_roles_label}")

        return errors

    def _check_operations(
        self, migration_name: str, operations, deployment_label: str, *, full: bool, attested: bool = False
    ) -> list[dict]:
        """Walk a migration's operations and return any convention violations.

        ``full=False`` is used for per-deployment passes: it only runs the cheap, deployment-
        agnostic checks (ON CLUSTER, missing _sql, mutations) so cloud-gated branches don't get
        flagged against legacy ALTER-TABLE flag rules they already shipped past. ``attested`` skips
        the mutation check for a migration carrying ``MUTATION_ATTESTATION_ATTRIBUTE``.
        """
        violations: list[dict] = []
        check_mutations = not attested and int(migration_name.split("_", 1)[0]) >= MIN_MUTATION_CHECKED_MIGRATION_NUMBER
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
            if check_mutations and (command := mutation_command(sql)):
                errors.append(mutation_error(command))
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

    @parameterized.expand(
        [
            ("drop_index", "ALTER TABLE sharded_events DROP INDEX IF EXISTS `bloom_filter_$session_id`", "DROP INDEX"),
            ("drop_column", "ALTER TABLE sharded_events DROP COLUMN IF EXISTS mat_foo", "DROP COLUMN"),
            ("drop_projection", "ALTER TABLE events DROP PROJECTION IF EXISTS p", "DROP PROJECTION"),
            ("materialize_index", "ALTER TABLE property_values MATERIALIZE INDEX idx", "MATERIALIZE INDEX"),
            ("materialize_column", "ALTER TABLE sharded_events MATERIALIZE COLUMN mat_foo", "MATERIALIZE COLUMN"),
            ("rename_column", "ALTER TABLE t RENAME COLUMN a TO b", "RENAME COLUMN"),
            ("modify_column_type", "ALTER TABLE t MODIFY COLUMN a Nullable(String)", "MODIFY COLUMN a N"),
            ("modify_ttl", "ALTER TABLE t MODIFY TTL timestamp + INTERVAL 30 DAY", "MODIFY TTL"),
            ("clear_column", "ALTER TABLE t CLEAR COLUMN a IN PARTITION '202609'", "CLEAR COLUMN"),
            ("update", "ALTER TABLE t UPDATE a = 1 WHERE b = 2", "UPDATE a ="),
            ("delete", "ALTER TABLE t DELETE WHERE team_id = 1", "DELETE WHERE"),
            ("lightweight_delete", "DELETE FROM t WHERE team_id = 1", "DELETE FROM"),
        ]
    )
    def test_mutation_command_is_detected(self, _name: str, sql: str, expected: str) -> None:
        assert mutation_command(sql) == expected

    @parameterized.expand(
        [
            (
                "add_index",
                "ALTER TABLE sharded_events ADD INDEX IF NOT EXISTS i `$session_id` TYPE bloom_filter GRANULARITY 1",
            ),
            ("add_column", "ALTER TABLE sharded_events ADD COLUMN IF NOT EXISTS mat_foo String"),
            (
                "modify_column_comment",
                "ALTER TABLE sharded_events MODIFY COLUMN mat_foo COMMENT 'column_materializer::foo'",
            ),
            ("modify_column_codec", "ALTER TABLE t MODIFY COLUMN a CODEC(ZSTD(3))"),
            ("modify_setting", "ALTER TABLE t MODIFY SETTING index_granularity = 8192"),
            ("drop_table", "DROP TABLE IF EXISTS t SYNC"),
            ("drop_partition", "ALTER TABLE t DROP PARTITION '202609'"),
            (
                "create_table_with_index",
                "CREATE TABLE t (a String, INDEX i a TYPE minmax GRANULARITY 1) ENGINE = MergeTree ORDER BY a",
            ),
        ]
    )
    def test_metadata_only_statement_is_not_a_mutation(self, _name: str, sql: str) -> None:
        assert mutation_command(sql) is None

    def test_mutation_in_a_migration_fails_unless_the_clickhouse_team_applied_it(self) -> None:
        operations = [
            run_sql_with_exceptions(
                "ALTER TABLE sharded_events DROP INDEX IF EXISTS `bloom_filter_$session_id`",
                sharded=True,
                is_alter_on_replicated_table=True,
            )
        ]

        violations = self._check_operations("0314_example", operations, "<default>", full=True)
        attested = self._check_operations("0314_example", operations, "<default>", full=True, attested=True)

        assert [v["errors"] for v in violations] == [[mutation_error("DROP INDEX")]]
        assert attested == []

    def test_mutations_are_allowed_in_migrations_before_the_cutoff(self) -> None:
        operations = [
            run_sql_with_exceptions(
                "ALTER TABLE property_values MATERIALIZE INDEX idx", sharded=False, is_alter_on_replicated_table=True
            )
        ]

        assert self._check_operations("0262_example", operations, "<default>", full=True) == []

    @staticmethod
    def _attested(module) -> bool:
        return bool(getattr(module, MUTATION_ATTESTATION_ATTRIBUTE, ""))

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
            violations += self._check_operations(
                name, operations, "<default>", full=True, attested=self._attested(module)
            )

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
                        violations += self._check_operations(
                            name, operations, deployment, full=False, attested=self._attested(module)
                        )
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
