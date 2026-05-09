# ruff: noqa: T201 allow print statements

import os
import sys

from django.core.management.base import BaseCommand
from django.db import migrations

from posthog.management.migration_analysis.analyzer import RiskAnalyzer
from posthog.management.migration_analysis.deprecated_field_filter import DeprecatedFieldFilter
from posthog.management.migration_analysis.formatters import ConsoleTreeFormatter, JsonFormatter
from posthog.management.migration_analysis.models import MigrationRisk, RiskLevel


class Command(BaseCommand):
    help = "Analyze migration operations and classify risk levels"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-blocked",
            action="store_true",
            help="Exit with code 1 if any blocked migrations found",
        )
        parser.add_argument(
            "--output-json",
            metavar="PATH",
            help="Also write structured analyzer output to PATH for programmatic consumers (CI, agents, etc.)",
        )

    def handle(self, *args, **options):
        json_path = options.get("output_json")

        # Check for missing migrations first
        missing_migrations_warning = self.check_missing_migrations()

        migrations = self.get_unapplied_migrations()

        if not migrations and not missing_migrations_warning:
            # No migrations to analyze. Still emit empty JSON so consumers can
            # distinguish "analyzer ran, nothing to report" from "analyzer failed".
            self.write_json_report([], json_path)
            return

        # Print missing migrations warning if present
        if missing_migrations_warning:
            print(missing_migrations_warning)
            if not migrations:
                self.write_json_report([], json_path)
                return

        # Check batch-level policies (e.g., multiple migrations per app)
        batch_policy_violations = self.check_batch_policies(migrations)
        if batch_policy_violations:
            print("\n📋 POLICY VIOLATIONS:")
            for violation in batch_policy_violations:
                print(f"  {violation}")
            print()  # Add spacing before migration analysis

        results = self.analyze_loaded_migrations(migrations)

        if not results:
            self.write_json_report([], json_path)
            return

        self.print_report(results)
        self.write_json_report(results, json_path)

        if options.get("fail_on_blocked"):
            blocked = [r for r in results if r.level == RiskLevel.BLOCKED]
            if blocked or batch_policy_violations:
                sys.exit(1)

    def check_batch_policies(self, migrations: list[tuple[str, migrations.Migration]]) -> list[str]:
        """Check policies that apply to the batch of migrations."""
        # No batch-level policies currently enforced.
        # SingleMigrationPolicy was removed to allow splitting atomic and non-atomic
        # operations into separate migrations (e.g., schema changes + concurrent index).
        return []

    def get_unapplied_migrations(self) -> list[tuple[str, "migrations.Migration"]]:
        """Get all unapplied migrations using Django's migration executor."""
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        try:
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except Exception:
            # Return empty list if can't connect to DB or load migrations
            return []

        # Return list of (label, migration_object) tuples
        # label is like "app_label.migration_name" for reporting
        return [(f"{migration.app_label}.{migration.name}", migration) for migration, backwards in plan]

    def analyze_loaded_migrations(self, migrations: list[tuple[str, migrations.Migration]]) -> list[MigrationRisk]:
        """Analyze a list of loaded migrations."""
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        analyzer = RiskAnalyzer()
        results = []

        # Get migration loader for enhanced validation
        try:
            executor = MigrationExecutor(connection)
            loader = executor.loader
        except Exception:
            loader = None

        for label, migration in migrations:
            # Best-effort: a single un-analyzable migration must not abort the run,
            # otherwise handle() never reaches write_json_report() and the
            # downstream Migration risk check is never published — leaving
            # stamphog stuck in WAITING with no bridge retrigger.
            try:
                file_path = self._migration_file_path(migration)
                if loader:
                    risk = analyzer.analyze_migration_with_context(migration, label, loader, file_path=file_path)
                else:
                    risk = analyzer.analyze_migration(migration, label, file_path=file_path)
                results.append(risk)
            except Exception as e:
                print(f"## ⚠️ Error analyzing migration {label}: {e}", file=sys.stderr)
                continue

        return results

    def _migration_file_path(self, migration) -> str | None:
        """Resolve the repo-relative file path for a loaded Django migration.

        Uses the migration class's imported module rather than the loader so it
        works for any app — including products with custom MIGRATION_MODULES
        mappings, which still set __module__ to the actual import path.
        """
        module_name = getattr(migration.__class__, "__module__", None)
        if not module_name:
            return None
        module = sys.modules.get(module_name)
        absolute = getattr(module, "__file__", None)
        if not absolute:
            return None
        try:
            return os.path.relpath(absolute)
        except ValueError:
            # Cross-drive or otherwise unrelatable path — fall back to None
            # so consumers know we couldn't pin a path for this migration.
            return None

    def check_missing_migrations(self) -> str:
        """Check if there are model changes that need migrations."""
        import sys
        from io import StringIO

        from django.core.management import call_command

        # Capture stdout/stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_capture = StringIO()
        stderr_capture = StringIO()

        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture

            try:
                call_command("makemigrations", "--check", "--dry-run")
                # Exit code 0 means no migrations needed
                return ""
            except SystemExit:
                # Exit code 1 means migrations needed
                output = stdout_capture.getvalue()
                if output.strip():
                    # Filter out deprecated field removals
                    filtered_output = DeprecatedFieldFilter.filter_output(output)

                    if not filtered_output.strip():
                        return ""

                    # Prepend Summary for CI workflow, wrap Django's output in code block
                    return f"**Summary:** ⚠️ Missing migrations detected\n\n```\n{filtered_output}\n```\n\nRun `python manage.py makemigrations` to create them.\n"
                return ""
        except Exception:
            # Ignore other errors (e.g., can't connect to DB)
            return ""
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def print_report(self, results):
        """Print formatted risk report."""
        formatter = ConsoleTreeFormatter()
        output = formatter.format_report(results)
        print(output)

    def write_json_report(self, results: list[MigrationRisk], path: str | None) -> None:
        """Write structured analyzer output for programmatic consumers."""
        if not path:
            return
        with open(path, "w") as f:
            f.write(JsonFormatter().format_report(results))
