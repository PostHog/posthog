"""
Management command to verify flags cache consistency.

Compares cached flags data against database to detect discrepancies.

IMPORTANT: This command requires FLAGS_REDIS_URL to be set. It will error if the
dedicated flags cache is not configured to prevent misleading results.

Usage:
    # Verify all teams
    python manage.py verify_flags_cache

    # Verify specific teams
    python manage.py verify_flags_cache --team-ids 123 456 789

    # Sample random teams
    python manage.py verify_flags_cache --sample 100

    # Verbose output (show full diffs)
    python manage.py verify_flags_cache --verbose

    # Automatically fix cache issues
    python manage.py verify_flags_cache --fix

    # Fix specific teams
    python manage.py verify_flags_cache --team-ids 123 456 --fix
"""

from typing import override

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.models.feature_flag.flags_cache import FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, verify_team_flags


class Command(BaseHyperCacheCommand):
    help = "Verify flags cache consistency against database"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_verify_arguments(parser)

    @override
    def format_verbose_diff(self, diff: dict):
        """
        Format and print a single diff for verbose verification output.

        Handles the flags-specific diff structure which uses:
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
            # field_diffs is present only in verbose mode (which is the only context this method is called)
            field_diffs = diff.get("field_diffs", [])
            for field_diff in field_diffs:
                field_name = field_diff.get("field", "unknown_field")
                self.stdout.write(f"    Field: {field_name}")
                self.stdout.write(f"      DB:    {field_diff.get('db_value')}")
                self.stdout.write(f"      Cache: {field_diff.get('cached_value')}")
        else:
            # Fallback for unknown diff types
            self.stdout.write(f"  Flag '{flag_key}': {diff_type}")

    def handle(self, *args, **options):
        # Check if dedicated flags cache is configured (fail fast)
        if not self.check_dedicated_cache_configured():
            return

        team_ids = options.get("team_ids")
        sample_size = options.get("sample")
        verbose = options.get("verbose", False)
        fix = options.get("fix", False)

        # Validate input arguments to prevent resource exhaustion
        if sample_size is not None:
            if not self.validate_sample_size(sample_size):
                return

        # Use the generic verification framework
        self.run_verification(
            team_ids=team_ids,
            sample_size=sample_size,
            verbose=verbose,
            fix=fix,
        )

    # Implement required methods for verification framework

    def get_hypercache_config(self):
        """Return the HyperCache management configuration."""
        return FLAGS_HYPERCACHE_MANAGEMENT_CONFIG

    def verify_team(self, team, verbose: bool, batch_data: dict | None = None) -> dict:
        """Verify a single team's flags cache against the database."""
        return verify_team_flags(team, batch_data, verbose=verbose)
