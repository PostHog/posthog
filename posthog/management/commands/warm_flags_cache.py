"""
Management command to warm the flags cache.

IMPORTANT: This command requires FLAGS_REDIS_URL to be set. It will error if the
dedicated flags cache is not configured to prevent warming the wrong cache.

Usage:
    # Initial cache warm (preserves existing caches)
    python manage.py warm_flags_cache

    # Warm specific teams
    python manage.py warm_flags_cache --team-ids 12345 67890

    # Schema changes (invalidates all caches first)
    python manage.py warm_flags_cache --invalidate-first

    # Custom batch size and TTL range
    python manage.py warm_flags_cache --batch-size 200 --min-ttl-days 6 --max-ttl-days 8
"""

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.models.feature_flag.flags_cache import (
    _get_feature_flags_for_teams_batch,
    flags_hypercache,
    update_flags_cache,
    warm_all_flags_caches,
)


class Command(BaseHyperCacheCommand):
    help = "Warm flags cache for all teams (initial build or schema migration)"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_warm_arguments(parser)

    def handle(self, *args, **options):
        team_ids = options.get("team_ids")
        batch_size = options["batch_size"]
        invalidate_first = options["invalidate_first"]
        stagger_ttl = not options["no_stagger"]
        min_ttl_days = options["min_ttl_days"]
        max_ttl_days = options["max_ttl_days"]

        # Validate input arguments to prevent resource exhaustion
        if not self.validate_batch_size(batch_size):
            return
        if not self.validate_ttl_range(min_ttl_days, max_ttl_days):
            return

        # Check if dedicated flags cache is configured
        if not self.check_dedicated_cache_configured(
            "warms the dedicated flags cache used by the Rust feature-flags service"
        ):
            return

        # Use the generic warming framework
        self.run_warm(
            team_ids=team_ids,
            batch_size=batch_size,
            invalidate_first=invalidate_first,
            stagger_ttl=stagger_ttl,
            min_ttl_days=min_ttl_days,
            max_ttl_days=max_ttl_days,
        )

    # Implement required methods for warming framework

    def get_cache_name(self) -> str:
        """Return name of cache for display purposes."""
        return "flags"

    def get_warm_all_fn(self):
        """Return function to warm all teams' caches."""
        return warm_all_flags_caches

    def get_update_cache_fn(self):
        """Return function to update a single team's cache."""
        return update_flags_cache

    def get_warm_batch_data_fn(self):
        """Return function to batch-load flags for multiple teams."""
        return _get_feature_flags_for_teams_batch

    def warm_team_with_batch_data(self, team, batch_data: dict, ttl: int | None):
        """Warm a single team's cache using pre-loaded batch data."""
        if team.id in batch_data:
            flags_hypercache.set_cache_value(team, batch_data[team.id], ttl=ttl)
        else:
            # Fall back to regular update if team not in batch data
            update_flags_cache(team, ttl=ttl)
