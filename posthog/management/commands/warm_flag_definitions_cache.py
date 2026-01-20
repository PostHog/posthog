"""
Management command to warm the flag definitions cache.

This warms both cache variants (with and without cohorts) used for SDK local evaluation.

IMPORTANT: This command warms caches with dual-write support - data is written to both
the shared cache (Django reads) and the dedicated cache (Rust service reads).

Usage:
    # Initial cache warm (preserves existing caches)
    python manage.py warm_flag_definitions_cache

    # Warm specific teams
    python manage.py warm_flag_definitions_cache --team-ids 12345 67890

    # Schema changes (invalidates all caches first)
    python manage.py warm_flag_definitions_cache --invalidate-first

    # Warm only one variant
    python manage.py warm_flag_definitions_cache --variant with-cohorts
    python manage.py warm_flag_definitions_cache --variant without-cohorts

    # Custom batch size and TTL range
    python manage.py warm_flag_definitions_cache --batch-size 200 --min-ttl-days 6 --max-ttl-days 8
"""

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.models.feature_flag.local_evaluation import (
    FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
    FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG,
)


class Command(BaseHyperCacheCommand):
    help = "Warm flag definitions cache for all teams (initial build or schema migration)"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_warm_arguments(parser)
        parser.add_argument(
            "--variant",
            type=str,
            choices=["with-cohorts", "without-cohorts"],
            help="Warm only the specified variant (default: both)",
        )

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
        variant = options.get("variant")

        # Validate input arguments to prevent resource exhaustion
        if not self.validate_batch_size(batch_size):
            return
        if not self.validate_ttl_range(min_ttl_days, max_ttl_days):
            return

        # Determine which configs to warm
        configs_to_warm = []
        if variant == "with-cohorts":
            configs_to_warm = [(FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG, "with cohorts")]
        elif variant == "without-cohorts":
            configs_to_warm = [(FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG, "without cohorts")]
        else:
            # Warm both variants
            configs_to_warm = [
                (FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG, "with cohorts"),
                (FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG, "without cohorts"),
            ]

        # Warm each variant
        for config, variant_name in configs_to_warm:
            self.stdout.write(f"\n{'=' * 70}")
            self.stdout.write(self.style.SUCCESS(f"Warming flag definitions cache ({variant_name})"))
            self.stdout.write("=" * 70)

            # Store the config for get_hypercache_config()
            self._current_config = config

            self.run_warm(
                team_ids=team_ids,
                batch_size=batch_size,
                invalidate_first=invalidate_first,
                stagger_ttl=stagger_ttl,
                min_ttl_days=min_ttl_days,
                max_ttl_days=max_ttl_days,
            )

    def get_hypercache_config(self):
        """Return the HyperCache management configuration."""
        return getattr(self, "_current_config", FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG)
