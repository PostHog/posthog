import datetime

from django.db.models import Q
from django.utils import timezone

import dagster

from products.error_tracking.backend.models import ErrorTrackingSymbolSet

from dags.common import JobOwners


class SymbolSetSelectionConfig(dagster.Config):
    days_old: int = 30
    delete_unused: bool = False  # Delete symbol sets with null last_used
    batch_size: int = 10000  # Maximum number of sets to process, to prevent ooms


class SymbolSetDeletionConfig(dagster.Config):
    dry_run: bool = False


@dagster.asset
def symbol_sets_to_delete(config: SymbolSetSelectionConfig) -> list[ErrorTrackingSymbolSet]:
    cutoff_date = timezone.now() - datetime.timedelta(days=config.days_old)

    query_filter = Q(last_used__isnull=False) & Q(last_used__lt=cutoff_date)

    if config.delete_unused:
        query_filter = query_filter | (Q(last_used__isnull=True) & Q(created_at__lt=cutoff_date))

    symbol_sets = ErrorTrackingSymbolSet.objects.filter(query_filter).order_by("last_used")[: config.batch_size]

    return list(symbol_sets)


@dagster.op
def delete_symbol_sets_batch(
    context: dagster.OpExecutionContext,
    symbol_sets: list[ErrorTrackingSymbolSet],
    config: SymbolSetDeletionConfig,
) -> int:
    deleted_count = 0
    failed_count = 0

    for symbol_set in symbol_sets:
        last_used_str = symbol_set.last_used.isoformat() if symbol_set.last_used else "never"

        try:
            if config.dry_run:
                context.log.info(
                    f"DRY RUN: Would delete symbol set {symbol_set.id} "
                    f"(ref: {symbol_set.ref}, team: {symbol_set.team_id}, "
                    f"last_used: {last_used_str})"
                )
            else:
                # The model's delete() method handles S3 cleanup automatically
                context.log.info(
                    f"Deleting symbol set {symbol_set.id} "
                    f"(ref: {symbol_set.ref}, team: {symbol_set.team_id}, "
                    f"last_used: {last_used_str})"
                )
                symbol_set.delete()
                context.log.info("Deleted symbol set")

            deleted_count += 1

        except Exception as e:
            failed_count += 1
            context.log.exception(
                f"Failed to delete symbol set {symbol_set.id} "
                f"(ref: {symbol_set.ref}, team: {symbol_set.team_id}, "
                f"last_used: {last_used_str}): {str(e)}"
            )

    context.add_output_metadata(
        {
            "deleted_count": dagster.MetadataValue.int(deleted_count),
            "failed_count": dagster.MetadataValue.int(failed_count),
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
        }
    )

    if failed_count > 0:
        # We're mostly fine with failed deletes - deep in the "care about it eventually" bucket
        context.log.warning(f"Failed to delete {failed_count} symbol sets out of {len(symbol_sets)} total")

    return deleted_count


@dagster.asset(deps=[symbol_sets_to_delete])
def symbol_set_cleanup_results(
    context: dagster.AssetExecutionContext,
    symbol_sets_to_delete: list[ErrorTrackingSymbolSet],
    config: SymbolSetDeletionConfig,
) -> dagster.MaterializeResult:
    """
    Asset that performs the actual deletion and reports results.
    """
    if not symbol_sets_to_delete:
        context.log.info("No symbol sets found for deletion")
        return dagster.MaterializeResult(
            metadata={
                "objects_processed": dagster.MetadataValue.int(0),
                "objects_deleted": dagster.MetadataValue.int(0),
                "dry_run": dagster.MetadataValue.bool(config.dry_run),
            }
        )

    deleted_count = delete_symbol_sets_batch(
        context=dagster.build_op_context(), symbol_sets=symbol_sets_to_delete, config=config
    )

    return dagster.MaterializeResult(
        metadata={
            "objects_processed": dagster.MetadataValue.int(len(symbol_sets_to_delete)),
            "objects_deleted": dagster.MetadataValue.int(deleted_count),
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
        }
    )


# Create the job
symbol_set_cleanup_job = dagster.define_asset_job(
    name="symbol_set_cleanup_job",
    selection=[symbol_sets_to_delete.key, symbol_set_cleanup_results.key],
    tags={"owner": JobOwners.TEAM_ERROR_TRACKING.value},
)


# Create schedule - runs daily at 3 AM
@dagster.schedule(
    job=symbol_set_cleanup_job,
    cron_schedule="0 * * * *",  # Run every hour
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def daily_symbol_set_cleanup_schedule(context):
    """Schedule the symbol set cleanup job to run daily at 3 AM UTC."""
    return dagster.RunRequest(
        run_key=f"symbol_set_cleanup_{context.scheduled_execution_time.strftime('%Y%m%d_%H%M%S')}",
        run_config={
            "ops": {
                "symbol_sets_to_delete": {
                    "config": SymbolSetSelectionConfig(
                        days_old=30,
                        delete_unused=True,
                        batch_size=10000,
                    ).model_dump()
                },
                "symbol_set_cleanup_results": {"config": SymbolSetDeletionConfig(dry_run=False).model_dump()},
            }
        },
    )
