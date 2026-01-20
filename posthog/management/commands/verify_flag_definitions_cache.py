"""
Management command to verify flag definitions cache consistency.

Compares cached flag definitions data against database to detect discrepancies.
Verifies both cache variants (with and without cohorts) used for SDK local evaluation.

Usage:
    # Verify all teams
    python manage.py verify_flag_definitions_cache

    # Verify specific teams
    python manage.py verify_flag_definitions_cache --team-ids 123 456 789

    # Sample random teams
    python manage.py verify_flag_definitions_cache --sample 100

    # Verify only one variant
    python manage.py verify_flag_definitions_cache --variant with-cohorts
    python manage.py verify_flag_definitions_cache --variant without-cohorts

    # Verbose output (show full diffs)
    python manage.py verify_flag_definitions_cache --verbose

    # Automatically fix cache issues
    python manage.py verify_flag_definitions_cache --fix
"""

from typing import Any

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.models.feature_flag.local_evaluation import (
    FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
    FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG,
    verify_team_flag_definitions,
)
from posthog.models.team import Team


class Command(BaseHyperCacheCommand):
    help = "Verify flag definitions cache consistency against database"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_verify_arguments(parser)
        parser.add_argument(
            "--variant",
            type=str,
            choices=["with-cohorts", "without-cohorts"],
            help="Verify only the specified variant (default: both)",
        )

    def handle(self, *args, **options):
        # Check if dedicated flags cache is configured (fail fast)
        if not self.check_dedicated_cache_configured():
            return

        team_ids = options.get("team_ids")
        sample_size = options.get("sample")
        verbose = options.get("verbose", False)
        fix = options.get("fix", False)
        variant = options.get("variant")

        # Validate input arguments to prevent resource exhaustion
        if sample_size is not None:
            if not self.validate_sample_size(sample_size):
                return

        # Determine which configs to verify
        configs_to_verify = []
        if variant == "with-cohorts":
            configs_to_verify = [(FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG, "with cohorts", True)]
        elif variant == "without-cohorts":
            configs_to_verify = [(FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG, "without cohorts", False)]
        else:
            # Verify both variants
            configs_to_verify = [
                (FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG, "with cohorts", True),
                (FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG, "without cohorts", False),
            ]

        # Verify each variant
        for config, variant_name, include_cohorts in configs_to_verify:
            self.stdout.write(f"\n{'=' * 70}")
            self.stdout.write(self.style.SUCCESS(f"Verifying flag definitions cache ({variant_name})"))
            self.stdout.write("=" * 70)

            # Store config and include_cohorts for the verify_team method
            self._current_config = config
            self._include_cohorts = include_cohorts

            self.run_verification(
                team_ids=team_ids,
                sample_size=sample_size,
                verbose=verbose,
                fix=fix,
            )

    def get_hypercache_config(self):
        """Return the HyperCache management configuration."""
        return getattr(self, "_current_config", FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG)

    def verify_team(self, team: Team, verbose: bool, batch_data: dict[int, Any] | None = None) -> dict[str, Any]:
        """Verify a single team's flag definitions cache against the database."""
        include_cohorts = getattr(self, "_include_cohorts", True)
        return verify_team_flag_definitions(
            team,
            db_batch_data=batch_data,
            include_cohorts=include_cohorts,
            verbose=verbose,
        )
