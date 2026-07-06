"""
One-shot backfill that writes already-built RemoteConfig.config blobs into the
dedicated flags Redis so the Rust feature-flags service stops falling through to
S3 on /flags config_response.

After the writer wiring fix (RemoteConfig.get_hypercache() now targets the
dedicated FLAGS_REDIS cache when configured), the dedicated cache is still cold
for teams that haven't been organically re-synced. This command warms it from the
persisted RemoteConfig.config column without calling build_config(), avoiding the
expense and side effects of a full rebuild across tens of thousands of teams.

Writes go through `HyperCache.set_cache_value_redis_only` with `track_expiry=True`,
which writes to Redis (plus the secondary mirror) and seeds the
`remote_config_cache_expiry` sorted set, but skips S3 — S3 already holds fresh data
via the normal sync() path, and the goal here is to populate the Redis tier the Rust
service reads first. A per-row S3 PUT would turn a fast Redis backfill into hours of
synchronous boto3 round-trips for tens of thousands of teams.

Race note: this reads `RemoteConfig.config` via a cursored snapshot and writes
it to Redis. If an organic `sync()` for the same team writes a newer config to
Redis between the row-read and Redis-write here, this backfill will overwrite
that newer value with the snapshot. The team self-heals on its next signal-
triggered sync, so the worst case is one sync-cycle of staleness — tolerable
for a one-shot backfill. Avoid running this during a fleet-wide config push.

Usage:
    # Warm all teams (sequential, with batching)
    python manage.py warm_remote_configs_cache

    # Warm specific teams
    python manage.py warm_remote_configs_cache --team-ids 12345 67890

    # Dry run (count rows, don't write)
    python manage.py warm_remote_configs_cache --dry-run

    # Tune batch size
    python manage.py warm_remote_configs_cache --batch-size 500
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.remote_config import RemoteConfig

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Warm the array/config.json HyperCache from persisted RemoteConfig rows (one-shot backfill)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            nargs="+",
            type=int,
            default=None,
            help="Restrict backfill to these team IDs. If omitted, warms every RemoteConfig row.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of rows fetched per DB batch. Default 1000.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count eligible rows without writing to the cache.",
        )

    def handle(self, *args, **options):
        team_ids: list[int] | None = options["team_ids"]
        batch_size: int = options["batch_size"]
        dry_run: bool = options["dry_run"]

        if batch_size <= 0 or batch_size > 10_000:
            raise CommandError("--batch-size must be between 1 and 10000")

        if FLAGS_DEDICATED_CACHE_ALIAS not in settings.CACHES:
            raise CommandError(
                "FLAGS_REDIS_URL is not configured. This command backfills the dedicated "
                "flags Redis the Rust feature-flags service reads. Without FLAGS_REDIS_URL "
                "set, RemoteConfig.get_hypercache() falls back to the default cache and "
                "this backfill would target the wrong Redis. Set FLAGS_REDIS_URL and re-run."
            )

        hypercache = RemoteConfig.get_hypercache()

        # Read api_token from the related Team in the same query to avoid N+1 lookups.
        # Exclude empty configs at the DB level so `total` matches the work to be done
        # (the next organic sync will write the __missing__ sentinel for empty rows).
        queryset = (
            RemoteConfig.objects.select_related("team")
            .only("team__api_token", "config")
            .exclude(config={})
            .order_by("team_id")
        )
        if team_ids is not None:
            queryset = queryset.filter(team_id__in=team_ids)

        total = queryset.count()
        self.stdout.write(f"Backfilling {total} RemoteConfig row(s){' (dry run)' if dry_run else ''}")

        warmed = 0
        failed = 0
        start = time.monotonic()

        # Use .iterator() with chunk_size to stream rows instead of materializing all in memory.
        for remote_config in queryset.iterator(chunk_size=batch_size):
            team = remote_config.team

            if dry_run:
                warmed += 1
                continue

            try:
                # Pass the Team (not the token) so track_expiry stamps the expiry sorted set.
                hypercache.set_cache_value_redis_only(team, remote_config.config, track_expiry=True)
                warmed += 1
            except Exception:
                failed += 1
                logger.exception(
                    "warm_remote_configs_cache: write failed",
                    team_id=team.id,
                )

            if warmed and warmed % 1000 == 0:
                elapsed = time.monotonic() - start
                rate = warmed / elapsed if elapsed > 0 else 0
                self.stdout.write(f"  ...warmed {warmed}/{total} ({rate:.0f}/s)")

        elapsed = time.monotonic() - start
        self.stdout.write(self.style.SUCCESS(f"Done in {elapsed:.1f}s. warmed={warmed} failed={failed}"))

        if failed:
            raise CommandError(f"{failed} row(s) failed to warm — see logs")
