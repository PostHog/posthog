import time

from django.core.management.base import BaseCommand

from posthog.models.exported_asset import ExportedAsset


class Command(BaseCommand):
    help = "Backfill expires_after for ExportedAssets that have NULL values"

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually perform the update. Without this flag, only a dry-run count is shown.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of records to process per batch (default: 1000)",
        )
        parser.add_argument(
            "--sleep-interval",
            type=float,
            default=0.5,
            help="Seconds to sleep between batches to reduce DB load (default: 0.5)",
        )

    def handle(self, *args, **options):
        live_run = options["live_run"]
        batch_size = options["batch_size"]
        sleep_interval = options["sleep_interval"]

        queryset = ExportedAsset.objects_including_ttl_deleted.filter(expires_after__isnull=True)
        total = queryset.count()

        self.stdout.write(f"Found {total} ExportedAssets with NULL expires_after")

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill!"))
            return

        if not live_run:
            self.stdout.write(self.style.WARNING("Dry run - use --live-run to execute the backfill"))
            return

        updated = 0
        start_time = time.time()
        batch: list[ExportedAsset] = []

        for asset in queryset.iterator(chunk_size=batch_size):
            expiry_datetime = asset.created_at + ExportedAsset.get_expiry_delta(asset.export_format)
            asset.expires_after = expiry_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
            batch.append(asset)

            if len(batch) >= batch_size:
                ExportedAsset.objects_including_ttl_deleted.bulk_update(batch, ["expires_after"])
                updated += len(batch)
                batch = []

                elapsed = time.time() - start_time
                rate = updated / elapsed if elapsed > 0 else 0
                remaining = (total - updated) / rate if rate > 0 else 0
                self.stdout.write(
                    f"Progress: {updated}/{total} ({100 * updated / total:.1f}%) - "
                    f"{rate:.1f} records/sec - ~{remaining:.0f}s remaining"
                )
                time.sleep(sleep_interval)

        if batch:
            ExportedAsset.objects_including_ttl_deleted.bulk_update(batch, ["expires_after"])
            updated += len(batch)

        elapsed = time.time() - start_time
        self.stdout.write(self.style.SUCCESS(f"Done! Updated {updated} ExportedAssets in {elapsed:.1f}s"))
