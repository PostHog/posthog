# ruff: noqa: T201 allow print statements

import sys

from django.core.management.base import BaseCommand

from posthog.management.migration_analysis.analyzer import RiskAnalyzer
from posthog.management.migration_analysis.discovery import MigrationDiscovery
from posthog.management.migration_analysis.formatters import ConsoleTreeFormatter
from posthog.management.migration_analysis.models import MigrationRisk, RiskLevel


class Command(BaseCommand):
    help = "Analyze migration operations and classify risk levels"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-blocked",
            action="store_true",
            help="Exit with code 1 if any blocked migrations found",
        )

    def handle(self, *args, **options):
        migration_paths = self.get_migration_paths()

        if not migration_paths:
            self.stdout.write("No migrations to analyze")
            return

        results = self.analyze_migrations(migration_paths)

        if not results:
            self.stdout.write("No migrations analyzed")
            return

        self.print_report(results)

        if options["fail_on_blocked"]:
            blocked = [r for r in results if r.level == RiskLevel.BLOCKED]
            if blocked:
                sys.exit(1)

    def get_migration_paths(self) -> list[str]:
        """Read migration paths from stdin"""
        return MigrationDiscovery.read_paths_from_stdin()

    def analyze_migrations(self, migration_paths: list[str]) -> list[MigrationRisk]:
        """Analyze a list of migration file paths"""
        analyzer = RiskAnalyzer()
        results = []

        # Process paths and load migrations using shared utility
        loaded_migrations = MigrationDiscovery.process_migration_paths(
            migration_paths,
            skip_invalid=False,
            fail_on_ci=True,
        )

        # Analyze each migration
        for migration_info, migration in loaded_migrations:
            risk = analyzer.analyze_migration(migration, migration_info.path)
            results.append(risk)

        return results

    def print_report(self, results):
        """Print formatted risk report."""
        formatter = ConsoleTreeFormatter()
        output = formatter.format_report(results)
        print(output)
