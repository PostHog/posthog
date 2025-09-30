# ruff: noqa: T201 allow print statements

import sys
import textwrap

from django.core.management.base import BaseCommand

from posthog.management.migration_analysis import MigrationDiscovery, MigrationRisk, RiskAnalyzer, RiskLevel


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

    def print_report(self, results: list[MigrationRisk]):
        safe = [r for r in results if r.level == RiskLevel.SAFE]
        review = [r for r in results if r.level == RiskLevel.NEEDS_REVIEW]
        blocked = [r for r in results if r.level == RiskLevel.BLOCKED]

        print("\n" + "=" * 80)
        print("Migration Risk Report")
        print("=" * 80)
        print(f"\nSummary: {len(safe)} Safe | {len(review)} Needs Review | {len(blocked)} Blocked\n")

        if blocked:
            level = RiskLevel.BLOCKED
            print(f"{level.color}{level.icon} {level.category.upper()}\033[0m")
            print()
            for risk in blocked:
                self.print_migration_detail(risk)

        if review:
            level = RiskLevel.NEEDS_REVIEW
            print(f"\n{level.color}{level.icon} {level.category.upper()}\033[0m")
            print()
            for risk in review:
                self.print_migration_detail(risk)

        if safe:
            level = RiskLevel.SAFE
            print(f"\n{level.color}{level.icon} {level.category.upper()}\033[0m")
            print()
            for risk in safe:
                self.print_migration_detail(risk)

        print()

    def print_migration_detail(self, risk: MigrationRisk):
        print(f"{risk.path}")

        # Print individual operations with tree structure
        for idx, op_risk in enumerate(risk.operations):
            # Add connecting line if there are combination risks and not the last operation
            prefix = "  │  " if risk.combination_risks and idx < len(risk.operations) - 1 else "  "

            details_str = ", ".join(
                f"{k}: {v}"
                for k, v in op_risk.details.items()
                if k != "sql"  # Don't print full SQL
            )
            if details_str:
                print(f"{prefix}└─ #{idx+1} {op_risk.type} (score: {op_risk.score})")
                print(f"{prefix}   {op_risk.reason}")
                print(f"{prefix}   {details_str}")
            else:
                print(f"{prefix}└─ #{idx+1} {op_risk.type} (score: {op_risk.score}): {op_risk.reason}")

        # Print combination warnings with connecting visual
        if risk.combination_risks:
            print("  │")
            print("  └──> \033[91m⚠️  COMBINATION RISKS:\033[0m")
            for warning in risk.combination_risks:
                wrapped = textwrap.fill(warning, width=72, initial_indent="       ", subsequent_indent="       ")
                print(wrapped)

        print()
