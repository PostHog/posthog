"""
Management command to verify flag definitions cache consistency.

Compares cached flag definitions data against database to detect discrepancies.
By default verifies only the with-cohorts variant, which serves the vast majority of
traffic (the without-cohorts variant is deprecated). Both variants derive from the same
source data and share the same Celery update path, so checking one is a reliable
indicator of overall cache health. Use --variant both to verify both explicitly.

Usage:
    # Verify all teams
    python manage.py verify_flag_definitions_cache

    # Verify specific teams
    python manage.py verify_flag_definitions_cache --team-ids 123 456 789

    # Sample random teams
    python manage.py verify_flag_definitions_cache --sample 100

    # Verify a specific variant (default: with-cohorts)
    python manage.py verify_flag_definitions_cache --variant without-cohorts
    python manage.py verify_flag_definitions_cache --variant both

    # Verbose output (show full diffs)
    python manage.py verify_flag_definitions_cache --verbose

    # Automatically fix cache issues
    python manage.py verify_flag_definitions_cache --fix
"""

from typing import Any, override

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
            default="with-cohorts",
            choices=["with-cohorts", "without-cohorts", "both"],
            help="Which variant(s) to verify (default: with-cohorts)",
        )

    @override
    def format_verbose_diff(self, diff: dict):
        """
        Format and print a single diff for verbose verification output.

        Handles the flag-definitions diff structure which uses:
        - type: MISSING_IN_CACHE, STALE_IN_CACHE, or FIELD_MISMATCH
        - flag_key: The flag key
        - field_diffs: (for FIELD_MISMATCH) List of {field, db_value, cached_value}
        """
        diff_type = diff.get("type")
        flag_key = diff.get("flag_key") or str(diff.get("flag_id"))

        if diff_type == "MISSING_IN_CACHE":
            self.stdout.write(f"  Flag '{flag_key}': exists in DB but missing from cache")
        elif diff_type == "STALE_IN_CACHE":
            self.stdout.write(f"  Flag '{flag_key}': exists in cache but deleted from DB")
        elif diff_type == "FIELD_MISMATCH":
            self.stdout.write(f"  Flag '{flag_key}': field values differ")
            field_diffs = diff.get("field_diffs", [])
            for field_diff in field_diffs:
                field_name = field_diff.get("field", "unknown_field")
                self.stdout.write(f"    Field: {field_name}")
                self.stdout.write(f"      DB:    {field_diff.get('db_value')}")
                self.stdout.write(f"      Cache: {field_diff.get('cached_value')}")
        else:
            # Fallback for unknown diff types (e.g., COHORTS_MISMATCH, GROUP_TYPE_MAPPING_MISMATCH)
            self.stdout.write(f"  Flag '{flag_key}': {diff_type}")

    def handle(self, *args, **options):
        # No check_dedicated_cache_configured() needed — flag definitions use the
        # default cache (REDIS_URL), not the dedicated flags cache (FLAGS_REDIS_URL).
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
        if variant == "with-cohorts":
            configs_to_verify = [(FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG, "with cohorts", True)]
        elif variant == "without-cohorts":
            configs_to_verify = [(FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG, "without cohorts", False)]
        else:  # "both"
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
            # Note: Not thread-safe, but management commands run single-threaded
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
