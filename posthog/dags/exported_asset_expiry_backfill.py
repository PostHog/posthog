import gc
import time

import dagster

from posthog.dags.common import JobOwners
from posthog.models.exported_asset import ExportedAsset


class ExportedAssetExpiryBackfillConfig(dagster.Config):
    batch_size: int = 1000
    sleep_interval: float = 0.5


@dagster.op
def get_null_expiry_count(
    context: dagster.OpExecutionContext,
) -> int:
    total = ExportedAsset.objects_including_ttl_deleted.filter(expires_after__isnull=True).count()

    context.log.info(f"Found {total} ExportedAssets with NULL expires_after")
    context.add_output_metadata(
        {
            "total_assets": dagster.MetadataValue.int(total),
        }
    )

    return total


@dagster.op
def backfill_expiry_batch(
    context: dagster.OpExecutionContext,
    config: ExportedAssetExpiryBackfillConfig,
    total: int,
) -> dict:
    if total == 0:
        context.log.info("Nothing to backfill!")
        return {"updated": 0, "elapsed": 0.0}

    batch_size = config.batch_size
    sleep_interval = config.sleep_interval
    updated = 0
    start_time = time.time()

    while True:
        batch = list(
            ExportedAsset.objects_including_ttl_deleted.filter(expires_after__isnull=True)
            .only("id", "created_at", "export_format")
            .order_by("id")[:batch_size]
        )

        if not batch:
            break

        for asset in batch:
            expiry_datetime = asset.created_at + ExportedAsset.get_expiry_delta(asset.export_format)
            asset.expires_after = expiry_datetime.replace(hour=0, minute=0, second=0, microsecond=0)

        ExportedAsset.objects_including_ttl_deleted.bulk_update(batch, ["expires_after"])
        updated += len(batch)

        del batch
        gc.collect()

        elapsed = time.time() - start_time
        rate = updated / elapsed if elapsed > 0 else 0
        remaining = (total - updated) / rate if rate > 0 else 0
        context.log.info(
            f"Progress: {updated}/{total} ({100 * updated / total:.1f}%) - "
            f"{rate:.1f} records/sec - ~{remaining:.0f}s remaining"
        )

        time.sleep(sleep_interval)

    elapsed = time.time() - start_time
    context.log.info(f"Done! Updated {updated} ExportedAssets in {elapsed:.1f}s")
    context.add_output_metadata(
        {
            "updated": dagster.MetadataValue.int(updated),
            "elapsed_seconds": dagster.MetadataValue.float(elapsed),
        }
    )

    return {"updated": updated, "elapsed": elapsed}


@dagster.job(tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value})
def exported_asset_expiry_backfill_job():
    total = get_null_expiry_count()
    backfill_expiry_batch(total)
