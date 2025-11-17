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
from posthog.models.feature_flag.flags_cache import FLAGS_HYPERCACHE_MANAGEMENT_CONFIG


class Command(BaseHyperCacheCommand):
    help = "Warm flags cache for all teams (initial build or schema migration)"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_warm_arguments(parser)

    def handle(self, *args, **options):
        # Check if dedicated flags cache is configured (fail fast)
        if not self.check_dedicated_cache_configured():
            return

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

    def get_hypercache_config(self):
        """Return the HyperCache management configuration."""
        return FLAGS_HYPERCACHE_MANAGEMENT_CONFIG
