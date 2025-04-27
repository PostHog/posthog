from django.core.management.base import BaseCommand, CommandError
from posthog.redis import get_client
import random
import logging
import argparse

from structlog import get_logger

logger = get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Set TTL on old idle group_data_cache_v2 keys that are missing a TTL. Supports --dry-run. Adds random TTL to avoid expiration storms."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Only report how many keys would be updated, without modifying Redis.",
        )
        parser.add_argument(
            "--idle-threshold-days",
            type=int,
            default=90,
            help="Minimum idle time in days for a key to be considered stale.",
        )
        parser.add_argument(
            "--min-ttl-days",
            type=int,
            default=2,
            help="Minimum TTL in days to set on stale keys.",
        )
        parser.add_argument(
            "--max-ttl-days",
            type=int,
            default=4,
            help="Maximum TTL in days to set on stale keys.",
        )

    def _gather_keys_with_no_ttl(self, keys) -> list[dict]:
        pipe = self._redis_client.pipeline()
        decoded_keys = []
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            decoded_keys.append(key)
            pipe.object("idletime", key)
            pipe.ttl(key)
        redis_results = pipe.execute()
        # Build a list of dicts for easier consumption
        results = []
        for i, key in enumerate(decoded_keys):
            # TRICKY: we get idletime and ttl in pairs
            # so to look up the idletime for key1, we need to get redis_results[2 * i]
            # and the ttl for key1, we need to get redis_results[2 * i + 1]
            idletime = redis_results[2 * i]
            ttl = redis_results[2 * i + 1]
            if ttl != -1:
                # if a key has a ttl, it's not stale
                continue
            results.append({"key": key, "idletime": idletime, "ttl": ttl})
        return results

    def _expire_idle_keys(self, results: list[dict]) -> tuple[int, int]:
        """
        Expire idle keys based on their idletime and ttl.
        """
        checked = 0
        updated = 0
        pipe = self._redis_client.pipeline()
        keys_to_expire = []

        for result in results:
            key = result["key"]
            idletime = result["idletime"]
            ttl = result["ttl"]

            if idletime is None:
                continue  # Key disappeared between SCAN and OBJECT IDLETIME

            if idletime > self._idle_threshold_seconds:
                if self._dry_run:
                    updated += 1
                else:
                    if ttl == -1:
                        random_ttl = random.randint(self._ttl_min_seconds, self._ttl_max_seconds)
                        pipe.expire(key, random_ttl)
                        keys_to_expire.append(key)
                        updated += 1

            checked += 1

            if checked % 1000 == 0:
                logger.info("Checked keys", checked=checked, updated=updated, dry_run=self._dry_run)

        if not self._dry_run and keys_to_expire:
            pipe.execute()

        return checked, updated

    def handle(self, *args, **options):
        logger.info(
            f"Starting scan fix_stale_group_cache",
        )

        min_ttl_days = options["min_ttl_days"]
        max_ttl_days = options["max_ttl_days"]
        if min_ttl_days > max_ttl_days:
            raise CommandError("--min-ttl-days cannot be greater than --max-ttl-days")

        self._redis_client = get_client()
        logger.info("Redis connection info", connection=str(self._redis_client.connection_pool))

        idle_threshold_days = options["idle_threshold_days"]
        self._idle_threshold_seconds = idle_threshold_days * 24 * 3600

        self._ttl_min_seconds = min_ttl_days * 24 * 3600
        self._ttl_max_seconds = max_ttl_days * 24 * 3600

        self._dry_run = options["dry_run"]

        cursor = 0

        # so, we'll scan 500k pages of 1000 keys each, or a max of 500M keys
        # at least an order of magnitude more than we need
        # but means that if the cursor is not advancing, we'll break out of the loop
        page_size = 1000
        max_iterations = 500_000
        iteration = 0

        logger.info(
            f"Starting scan. Dry run is set to {self._dry_run}. {'Will change TTL' if not self._dry_run else 'Will not change TTL'}",
            idle_threshold_days=idle_threshold_days,
            min_ttl_days=min_ttl_days,
            max_ttl_days=max_ttl_days,
        )

        checked = 0
        updated = 0

        while True:
            # SCAN does NOT affect key idle time.
            cursor, keys = self._redis_client.scan(cursor=cursor, match="group_data_cache_v2*", count=page_size)

            results = self._gather_keys_with_no_ttl(keys)

            (page_checked, page_updated) = self._expire_idle_keys(results)
            checked += page_checked
            updated += page_updated

            iteration += 1
            if cursor == 0 or iteration >= max_iterations:
                if iteration >= max_iterations:
                    logger.warn("Max iterations reached, breaking out of scan loop", iteration=iteration)
                break

        logger.info("Done", checked=checked, updated=updated, dry_run=self._dry_run)
