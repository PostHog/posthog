# ruff: noqa: T201 allow print statements

import sys

from django.core.management.base import BaseCommand
from django.db import migrations

from posthog.management.migration_analysis.analyzer import RiskAnalyzer
from posthog.management.migration_analysis.formatters import ConsoleTreeFormatter
from posthog.management.migration_analysis.models import MigrationRisk, RiskLevel
from posthog.management.migration_analysis.policies import SingleMigrationPolicy


class Command(BaseCommand):
    help = "Analyze migration operations and classify risk levels"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-blocked",
            action="store_true",
            help="Exit with code 1 if any blocked migrations found",
        )

    def handle(self, *args, **options):
        migrations = self.get_unapplied_migrations()

        # Check for missing migrations first
        missing_migrations_warning = self.check_missing_migrations()

        if not migrations and not missing_migrations_warning:
            # Return silently when no migrations to analyze and no missing migrations (for CI)
            return

        # Print missing migrations warning if present
        if missing_migrations_warning:
            print(missing_migrations_warning)
            if not migrations:
                # If only missing migrations, exit early
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
            # Return silently when no results (for CI)
            return

        self.print_report(results)

        if options.get("fail_on_blocked"):
            blocked = [r for r in results if r.level == RiskLevel.BLOCKED]
            if blocked or batch_policy_violations:
                sys.exit(1)

    def check_batch_policies(self, migrations: list[tuple[str, migrations.Migration]]) -> list[str]:
        """Check policies that apply to the batch of migrations."""
        # Count migrations per app
        app_counts: dict[str, int] = {}
        for _label, migration in migrations:
            app_label = migration.app_label
            app_counts[app_label] = app_counts.get(app_label, 0) + 1

        policy = SingleMigrationPolicy(app_counts)
        return policy.check_batch()

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
            if loader:
                risk = analyzer.analyze_migration_with_context(migration, label, loader)
            else:
                risk = analyzer.analyze_migration(migration, label)
            results.append(risk)

        return results

    def check_missing_migrations(self) -> str:
        """Check if there are model changes that need migrations."""
        from django.apps import apps
        from django.db import connection
        from django.db.migrations.autodetector import MigrationAutodetector
        from django.db.migrations.loader import MigrationLoader
        from django.db.migrations.state import ProjectState

        try:
            # Load migration graph
            loader = MigrationLoader(connection, ignore_no_migrations=True)

            # Detect changes
            autodetector = MigrationAutodetector(
                loader.project_state(),
                ProjectState.from_apps(apps),
            )
            changes = autodetector.changes(graph=loader.graph)

            if not changes:
                return ""  # No missing migrations

            # Format the detected changes
            output_lines = ["⚠️  MISSING MIGRATIONS DETECTED\n"]
            output_lines.append("Model changes have been detected that require new migrations:\n")

            for app_label, app_migrations in changes.items():
                output_lines.append(f"\nMigrations for '{app_label}':")
                for migration in app_migrations:
                    for operation in migration.operations:
                        output_lines.append(f"  - {operation.describe()}")

            output_lines.append("\nRun `python manage.py makemigrations` to create them.\n")
            return "\n".join(output_lines)

        except Exception:
            # Ignore errors (e.g., can't connect to DB)
            return ""

    def print_report(self, results):
        """Print formatted risk report."""
        formatter = ConsoleTreeFormatter()
        output = formatter.format_report(results)
        print(output)
