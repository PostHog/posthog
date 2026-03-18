"""
Management command to verify team metadata cache consistency.

Compares cached data against database to detect discrepancies.

IMPORTANT: This command requires FLAGS_REDIS_URL to be set. It will error if the
dedicated flags cache is not configured to prevent misleading results.

Usage:
    # Verify all teams
    python manage.py verify_team_metadata_cache

    # Verify specific teams
    python manage.py verify_team_metadata_cache --team-ids 123 456 789

    # Sample random teams
    python manage.py verify_team_metadata_cache --sample 100

    # Verbose output (show full diffs)
    python manage.py verify_team_metadata_cache --verbose

    # Automatically fix cache issues
    python manage.py verify_team_metadata_cache --fix

    # Fix specific teams
    python manage.py verify_team_metadata_cache --team-ids 123 456 --fix
"""

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.storage.team_metadata_cache import TEAM_HYPERCACHE_MANAGEMENT_CONFIG, verify_team_metadata


class Command(BaseHyperCacheCommand):
    help = "Verify team metadata cache consistency against database"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_verify_arguments(parser)

    def handle(self, *args, **options):
        # Check if dedicated cache is configured (fail fast)
        if not self.check_dedicated_cache_configured():
            return

        team_ids = options.get("team_ids")
        sample_size = options.get("sample")
        verbose = options.get("verbose", False)
        fix = options.get("fix", False)

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
        return TEAM_HYPERCACHE_MANAGEMENT_CONFIG

    def verify_team(self, team, verbose: bool, batch_data: dict | None = None) -> dict:
        """Verify a single team's metadata cache against the database."""
        return verify_team_metadata(team, batch_data, verbose=verbose)
