# ruff: noqa: T201 allow print statements

import sys

from django.core.management.base import BaseCommand

from posthog.management.migration_analysis.analyzer import RiskAnalyzer
from posthog.management.migration_analysis.discovery import MigrationDiscovery
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
        migration_paths = self.get_migration_paths()

        if not migration_paths:
            # Return silently when no migrations to analyze (for CI)
            return

        # Check batch-level policies (e.g., multiple migrations)
        batch_policy_violations = self.check_batch_policies(migration_paths)
        if batch_policy_violations:
            print("\n📋 POLICY VIOLATIONS:")
            for violation in batch_policy_violations:
                print(f"  {violation}")
            if options.get("fail_on_blocked"):
                sys.exit(1)
            return

        results = self.analyze_migrations(migration_paths)

        if not results:
            # Return silently when no results (for CI)
            return

        self.print_report(results)

        if options.get("fail_on_blocked"):
            blocked = [r for r in results if r.level == RiskLevel.BLOCKED]
            if blocked:
                sys.exit(1)

    def get_migration_paths(self) -> list[str]:
        """Read migration paths from stdin"""
        return MigrationDiscovery.read_paths_from_stdin()

    def check_batch_policies(self, migration_paths: list[str]) -> list[str]:
        """Check policies that apply to the batch of migrations."""
        policy = SingleMigrationPolicy(len(migration_paths))
        return policy.check_batch()

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
