import os

from django.core.management.base import BaseCommand

import structlog

from posthog.redis import get_client

logger = structlog.get_logger(__name__)


def get_cookieless_redis_client():
    """Get Redis client for cookieless instance."""
    cookieless_host = os.getenv("COOKIELESS_REDIS_HOST", "")

    if not cookieless_host:
        raise ValueError(
            "COOKIELESS_REDIS_HOST environment variable is not set. "
            "This command requires explicit cookieless Redis configuration."
        )

    cookieless_port = os.getenv("COOKIELESS_REDIS_PORT", "6379")
    redis_url = f"redis://{cookieless_host}:{cookieless_port}/"
    logger.info(f"Connecting to cookieless Redis: {cookieless_host}:{cookieless_port}")
    return get_client(redis_url)


class Command(BaseCommand):
    help = "Extend TTL for cookieless Redis keys when upgrading from 24h to 72h ingestion lag support"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without modifying Redis keys",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of keys to process per batch (default: 1000)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        # Show which Redis instance we're connecting to
        cookieless_host = os.getenv("COOKIELESS_REDIS_HOST", "")
        cookieless_port = os.getenv("COOKIELESS_REDIS_PORT", "6379")
        self.stdout.write(self.style.SUCCESS(f"Connecting to cookieless Redis: {cookieless_host}:{cookieless_port}"))

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

        redis_client = get_cookieless_redis_client()

        # Define key patterns and their TTL extensions
        key_configs = [
            {
                "pattern": "cookieless_salt:*",
                "extension_seconds": 172800,  # +48 hours (24h → 72h)
                "description": "Salt keys",
            },
            {
                "pattern": "cklss:*",
                "extension_seconds": 172800,  # +48 hours (24h → 72h)
                "description": "Session keys",
            },
            {
                "pattern": "cklsi:*",
                "extension_seconds": 180000,  # +50 hours (70h → 120h)
                "description": "Identifies keys",
            },
        ]

        total_processed = 0
        total_extended = 0
        total_skipped = 0

        for config in key_configs:
            pattern = config["pattern"]
            extension_seconds = config["extension_seconds"]
            description = config["description"]

            self.stdout.write(f"\nProcessing {description} (pattern: {pattern})...")

            processed, extended, skipped = self._process_pattern(
                redis_client, pattern, extension_seconds, batch_size, dry_run
            )

            total_processed += processed
            total_extended += extended
            total_skipped += skipped

            self.stdout.write(
                self.style.SUCCESS(f"  {description}: {processed} processed, {extended} extended, {skipped} skipped")
            )

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(f"SUMMARY:"))
        self.stdout.write(f"  Total keys processed: {total_processed}")
        self.stdout.write(f"  Total keys extended: {total_extended}")
        self.stdout.write(f"  Total keys skipped: {total_skipped}")
        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN - No changes were made"))
        self.stdout.write("=" * 60)

    def _process_pattern(self, redis_client, pattern, extension_seconds, batch_size, dry_run):
        """Scan and extend TTL for keys matching the pattern"""
        cursor = 0
        processed = 0
        extended = 0
        skipped = 0

        while True:
            cursor, keys = redis_client.scan(cursor, match=pattern, count=batch_size)

            for key in keys:
                processed += 1

                # Get current TTL
                current_ttl = redis_client.ttl(key)

                # Skip if key has no TTL (-1) or doesn't exist (-2)
                if current_ttl < 0:
                    skipped += 1
                    logger.debug(f"Skipping key {key}: TTL={current_ttl}")
                    continue

                # Calculate new TTL
                new_ttl = current_ttl + extension_seconds

                if dry_run:
                    logger.info(f"[DRY RUN] Would extend {key}: {current_ttl}s → {new_ttl}s (+{extension_seconds}s)")
                    extended += 1
                else:
                    # Extend the TTL
                    redis_client.expire(key, new_ttl)
                    logger.info(f"Extended {key}: {current_ttl}s → {new_ttl}s")
                    extended += 1

            # Report progress every batch
            if processed > 0 and processed % batch_size == 0:
                self.stdout.write(f"  Progress: {processed} keys processed...")

            # Break when scan completes
            if cursor == 0:
                break

        return processed, extended, skipped
