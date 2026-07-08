"""
Management command to warm the flag definitions cache used for SDK local evaluation.

Usage:
    # Initial cache warm (preserves existing caches)
    python manage.py warm_flag_definitions_cache

    # Warm specific teams
    python manage.py warm_flag_definitions_cache --team-ids 12345 67890

    # Custom batch size and TTL range
    python manage.py warm_flag_definitions_cache --batch-size 200 --min-ttl-days 6 --max-ttl-days 8
"""

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand

from products.feature_flags.backend.local_evaluation import FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG


class Command(BaseHyperCacheCommand):
    help = "Warm flag definitions cache for all teams (initial build or schema migration)"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_warm_arguments(parser)

    def handle(self, *args, **options):
        # No check_dedicated_cache_configured() needed — flag definitions use the
        # default cache (REDIS_URL), not the dedicated flags cache (FLAGS_REDIS_URL).
        team_ids = options.get("team_ids")
        batch_size = options["batch_size"]
        stagger_ttl = not options["no_stagger"]
        min_ttl_days = options["min_ttl_days"]
        max_ttl_days = options["max_ttl_days"]

        # Validate input arguments to prevent resource exhaustion
        if not self.validate_batch_size(batch_size):
            return
        if not self.validate_ttl_range(min_ttl_days, max_ttl_days):
            return

        self.run_warm(
            team_ids=team_ids,
            batch_size=batch_size,
            stagger_ttl=stagger_ttl,
            min_ttl_days=min_ttl_days,
            max_ttl_days=max_ttl_days,
        )

    def get_hypercache_config(self):
        """Return the HyperCache management configuration."""
        return FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG
