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

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.models.feature_flag.flags_cache import FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, verify_team_flags


class Command(BaseHyperCacheCommand):
    help = "Verify flags cache consistency against database"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_verify_arguments(parser)

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
