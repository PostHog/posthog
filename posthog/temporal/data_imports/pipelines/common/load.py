from typing import TYPE_CHECKING, Any, Literal, Optional

from django.db.models import F

import pyarrow as pa
import pyarrow.compute as pc
import posthoganalytics
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.pipeline.utils import normalize_column_name
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema, process_incremental_value
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.data_warehouse.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
    from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse

    from products.data_warehouse.backend.models import ExternalDataSource

LOGGER = get_logger(__name__)


async def update_job_row_count(job_id: str, count: int, logger: FilteringBoundLogger) -> None:
    await logger.adebug(f"Updating rows_synced with +{count}")
    await database_sync_to_async_pool(
        lambda: ExternalDataJob.objects.filter(id=job_id).update(rows_synced=F("rows_synced") + count)
    )()


def get_incremental_field_value(
    schema: ExternalDataSchema | None, table: pa.Table, aggregate: Literal["max"] | Literal["min"] = "max"
) -> Any:
    if schema is None or schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH:
        return None

    incremental_field_name: str | None = schema.sync_type_config.get("incremental_field")
    if incremental_field_name is None:
        return None

    column = table[normalize_column_name(incremental_field_name)]
    processed_column = pa.array(
        [process_incremental_value(val, schema.incremental_field_type) for val in column.to_pylist()]
    )

    if aggregate == "max":
        last_value = pc.max(processed_column)
    elif aggregate == "min":
        last_value = pc.min(processed_column)
    else:
        raise Exception(f"Unsupported aggregate function for get_incremental_field_value: {aggregate}")

    return last_value.as_py()


def supports_partial_data_loading(schema: ExternalDataSchema) -> bool:
    """
    We should be able to roll this out to all source types in the future.
    Currently only Stripe sources support partial data loading.
    """
    return schema.source.source_type == ExternalDataSourceType.STRIPE


async def notify_revenue_analytics_that_sync_has_completed(
    schema: ExternalDataSchema, source: "ExternalDataSource", logger: FilteringBoundLogger
) -> None:
    from posthog.temporal.data_imports.sources.stripe.constants import (
        CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    )

    try:

        @database_sync_to_async_pool
        def _check_and_notify():
            if (
                schema.name == STRIPE_CHARGE_RESOURCE_NAME
                and source.source_type == ExternalDataSourceType.STRIPE
                and source.revenue_analytics_config.enabled
                and not schema.team.revenue_analytics_config.notified_first_sync
            ):
                # For every admin in the org, send a revenue analytics ready event
                # This will trigger a Campaign in PostHog and send an email
                for user in schema.team.all_users_with_access():
                    if user.distinct_id is not None:
                        posthoganalytics.capture(
                            distinct_id=user.distinct_id,
                            event="revenue_analytics_ready",
                            properties={"source_type": source.source_type},
                        )

                # Mark the team as notified, avoiding spamming emails
                schema.team.revenue_analytics_config.notified_first_sync = True
                schema.team.revenue_analytics_config.save()

        await _check_and_notify()
    except Exception as e:
        # Silently fail, we don't want this to crash the pipeline
        # Sending an email is not critical to the pipeline
        await logger.aexception(f"Error notifying revenue analytics that sync has completed: {e}")
        capture_exception(e)


async def run_post_load_operations(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_helper: "Optional[DeltaTableHelper]",
    row_count: int,
    file_uris: list[str],
    table_schema_dict: dict[str, str],
    resource_name: str,
    logger: FilteringBoundLogger,
    last_incremental_field_value: Any = None,
    resource: "Optional[SourceResponse]" = None,
) -> None:
    """
    Orchestrator function that runs all post-load operations:
        1. Compact delta table (if exists)
        2. Prepare S3 files for querying
        3. Update last_synced_at timestamp
        4. Notify revenue analytics (if applicable)
        5. Finalize incremental field values
        6. Validate schema and update table
    """
    from posthog.temporal.data_imports.pipelines.common.extract import finalize_desc_sort_incremental_value
    from posthog.temporal.data_imports.pipelines.pipeline_sync import (
        update_last_synced_at,
        validate_schema_and_update_table,
    )

    if delta_table_helper is None or delta_table_helper.get_delta_table() is None:
        logger.debug("No deltalake table, not continuing with post-run ops")
        return

    logger.debug("Triggering compaction and vacuuming on delta table")
    try:
        delta_table_helper.compact_table()
    except Exception as e:
        capture_exception(e)
        logger.exception(f"Compaction failed: {e}", exc_info=e)

    logger.debug(f"Preparing S3 files - total parquet files: {len(file_uris)}")
    queryable_folder = prepare_s3_files_for_querying(
        job.folder_path(),
        resource_name,
        file_uris,
        delete_existing=True,
        existing_queryable_folder=schema.table.queryable_folder if schema.table else None,
        logger=logger,
    )

    logger.debug("Updating last synced at timestamp on schema")
    await update_last_synced_at(job_id=str(job.id), schema_id=str(schema.id), team_id=job.team_id)

    logger.debug("Notifying revenue analytics that sync has completed")
    await notify_revenue_analytics_that_sync_has_completed(schema, source, logger)

    if resource is not None:
        await finalize_desc_sort_incremental_value(resource, schema, last_incremental_field_value, logger)

    logger.debug("Validating schema and updating table")
    await validate_schema_and_update_table(
        run_id=str(job.id),
        team_id=job.team_id,
        schema_id=schema.id,
        table_schema_dict=table_schema_dict,
        row_count=row_count,
        queryable_folder=queryable_folder,
        table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
    )
    logger.debug("Finished validating schema and updating table")
