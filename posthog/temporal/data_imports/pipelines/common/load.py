from typing import TYPE_CHECKING, Any, Literal, Optional

from django.db.models import F

import pyarrow as pa
import pyarrow.compute as pc
import posthoganalytics
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.helpers import sync_revenue_analytics_views
from posthog.temporal.data_imports.pipelines.pipeline.utils import normalize_column_name
from posthog.temporal.data_imports.pipelines.pipeline_sync import set_initial_sync_complete
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


async def _seed_cdc_companion_from_snapshot(
    schema: ExternalDataSchema,
    job: ExternalDataJob,
    source: "ExternalDataSource",
    snapshot_delta_table_helper: "DeltaTableHelper",
    logger: FilteringBoundLogger,
) -> None:
    """Populate the _cdc companion table with snapshot rows as synthetic INSERT events.

    Called after the initial full-refresh snapshot completes for a CDC schema that uses
    'cdc_only' or 'both' mode.  Any existing companion table is reset first so that a
    full resync always starts the _cdc history fresh from the new snapshot.

    Reads the snapshot in batches via PyArrow dataset scanning to avoid loading the
    entire table into memory.
    """
    import asyncio

    from posthog.temporal.data_imports.cdc.batcher import (
        CDC_OP_COLUMN,
        CDC_TIMESTAMP_COLUMN,
        DELETED_AT_COLUMN,
        DELETED_COLUMN,
        SCD2_VALID_FROM_COLUMN,
        SCD2_VALID_TO_COLUMN,
    )
    from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
    from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema

    snapshot_dt = await snapshot_delta_table_helper.get_delta_table()
    if snapshot_dt is None:
        return

    dataset = await asyncio.to_thread(snapshot_dt.to_pyarrow_dataset)

    # Strip any pre-existing CDC metadata columns from the snapshot (defensive).
    cdc_meta_cols = {
        CDC_OP_COLUMN,
        CDC_TIMESTAMP_COLUMN,
        DELETED_COLUMN,
        DELETED_AT_COLUMN,
        SCD2_VALID_FROM_COLUMN,
        SCD2_VALID_TO_COLUMN,
    }
    read_columns = [c for c in dataset.schema.names if c not in cdc_meta_cols]

    companion_resource_name = f"{schema.name}_cdc"
    companion_helper = DeltaTableHelper(
        resource_name=companion_resource_name,
        job=job,
        logger=logger,
    )

    # Reset so a full resync always starts the companion fresh.
    await companion_helper.reset_table()

    hogql_schema = HogQLSchema()
    total_rows = 0

    SEED_BATCH_SIZE = 50_000
    reader = await asyncio.to_thread(
        lambda: dataset.scanner(columns=read_columns, batch_size=SEED_BATCH_SIZE).to_reader()
    )

    def _read_next_batch(r: pa.RecordBatchReader) -> pa.RecordBatch | None:
        try:
            return r.read_next_batch()
        except StopIteration:
            return None

    # Use Unix epoch (0) for the seed timestamp so that any real WAL commit timestamp
    # is guaranteed to be greater.  Without this, seeded rows end up with
    # valid_from > valid_to when the first CDC event has a commit time that predates
    # the snapshot ingestion time (e.g. changes captured during the initial snapshot load).
    ts_type = pa.timestamp("us", tz="UTC")
    epoch_us = 0

    while True:
        batch = await asyncio.to_thread(_read_next_batch, reader)
        if batch is None:
            break

        batch_table = pa.Table.from_batches([batch])
        if batch_table.num_rows == 0:
            continue

        n = batch_table.num_rows
        batch_table = (
            batch_table.append_column(pa.field(CDC_OP_COLUMN, pa.string()), pa.array(["I"] * n, type=pa.string()))
            .append_column(pa.field(CDC_TIMESTAMP_COLUMN, ts_type), pa.array([epoch_us] * n, type=ts_type))
            .append_column(pa.field(DELETED_COLUMN, pa.bool_()), pa.array([False] * n, type=pa.bool_()))
            .append_column(pa.field(DELETED_AT_COLUMN, ts_type), pa.array([None] * n, type=ts_type))
            .append_column(pa.field(SCD2_VALID_FROM_COLUMN, ts_type), pa.array([epoch_us] * n, type=ts_type))
            .append_column(pa.field(SCD2_VALID_TO_COLUMN, ts_type), pa.array([None] * n, type=ts_type))
        )

        # Plain append — the companion table is freshly reset so there are no existing
        # rows to close, making SCD2 merge unnecessary.
        await companion_helper.write_to_deltalake(
            data=batch_table,
            write_type="append",
            should_overwrite_table=False,
            primary_keys=None,
        )
        hogql_schema.add_pyarrow_table(batch_table)
        total_rows += n

    if total_rows == 0:
        return

    file_uris = await companion_helper.get_file_uris()

    await run_post_load_operations(
        job=job,
        schema=schema,
        source=source,
        delta_table_helper=companion_helper,
        row_count=total_rows,
        file_uris=file_uris,
        table_schema_dict=hogql_schema.to_hogql_types(),
        resource_name=companion_resource_name,
        logger=logger,
        cdc_write_mode="scd2_append",
    )


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
    cdc_table_mode: Optional[str] = None,
    cdc_write_mode: Optional[str] = None,
) -> None:
    """
    Orchestrator function that runs all post-load operations:
        1. Compact delta table (if exists)
        2. Prepare S3 files for querying
        3. Update last_synced_at timestamp
        4. Notify revenue analytics (if applicable)
        5. Finalize incremental field values
        6. Validate schema and update table (or register CDC companion table)
        7. Sync revenue analytics views (if applicable)
    """
    from posthog.temporal.data_imports.pipelines.common.extract import finalize_desc_sort_incremental_value
    from posthog.temporal.data_imports.pipelines.helpers import build_table_name
    from posthog.temporal.data_imports.pipelines.pipeline_sync import (
        register_cdc_companion_table,
        update_last_synced_at,
        validate_schema_and_update_table,
    )
    from posthog.temporal.data_imports.pipelines.pipeline_v3.load.metrics import POST_LOAD_DURATION_SECONDS

    if delta_table_helper is None or await delta_table_helper.get_delta_table() is None:
        logger.debug("No deltalake table, not continuing with post-run ops")
        return

    # Detect CDC companion writes — scd2_append writes always go to the companion _cdc resource.
    # In this case we must NOT touch schema.table (the snapshot table) and must register the companion
    # table independently, otherwise we overwrite the snapshot queryable_folder with the SCD2 path.
    is_cdc_companion = cdc_write_mode == "scd2_append"

    logger.debug("Triggering compaction and vacuuming on delta table")
    try:
        with POST_LOAD_DURATION_SECONDS.labels(operation="compact").time():
            await delta_table_helper.compact_table()
    except Exception as e:
        capture_exception(e)
        logger.exception(f"Compaction failed: {e}", exc_info=e)

    if is_cdc_companion:
        # Look up the existing companion table's queryable_folder (not the main schema.table).
        # build_table_name accesses job.pipeline (FK), so do it inside the sync wrapper.
        _resource_name = resource_name

        @database_sync_to_async_pool
        def _get_companion_queryable_folder():
            name = build_table_name(job.pipeline, _resource_name)
            return (
                DataWarehouseTable.objects.filter(
                    team_id=job.team_id,
                    name=name,
                    external_data_source_id=job.pipeline.id,
                    deleted=False,
                )
                .values_list("queryable_folder", flat=True)
                .first()
            )

        existing_queryable_folder = await _get_companion_queryable_folder()
    else:
        existing_queryable_folder = await database_sync_to_async_pool(
            lambda: schema.table.queryable_folder if schema.table else None
        )()

    logger.debug(f"Preparing S3 files - total parquet files: {len(file_uris)}")
    with POST_LOAD_DURATION_SECONDS.labels(operation="prepare_s3").time():
        queryable_folder = await prepare_s3_files_for_querying(
            await database_sync_to_async_pool(job.folder_path)(),
            resource_name,
            file_uris,
            delete_existing=True,
            existing_queryable_folder=existing_queryable_folder,
            logger=logger,
        )

    logger.debug("Updating last synced at timestamp on schema")
    await update_last_synced_at(job_id=str(job.id), schema_id=str(schema.id), team_id=job.team_id)

    logger.debug("Notifying revenue analytics that sync has completed")
    await notify_revenue_analytics_that_sync_has_completed(schema, source, logger)

    if not schema.initial_sync_complete:
        await logger.adebug("Setting initial_sync_complete on schema")
        await set_initial_sync_complete(schema_id=schema.id, team_id=job.team_id)

    if resource is not None:
        await finalize_desc_sort_incremental_value(resource, schema, last_incremental_field_value, logger)

    if is_cdc_companion:
        logger.debug("Registering CDC companion table")
        with POST_LOAD_DURATION_SECONDS.labels(operation="validate_schema").time():
            await register_cdc_companion_table(
                run_id=str(job.id),
                team_id=job.team_id,
                schema_id=schema.id,
                resource_name=resource_name,
                row_count=row_count,
                table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                queryable_folder=queryable_folder,
                table_schema_dict=table_schema_dict,
                set_as_schema_table=schema.cdc_table_mode == "cdc_only",
            )
        logger.debug("Finished registering CDC companion table")
    else:
        # For cdc_only mode during the initial load, skip registering the consolidated
        # DataWarehouseTable — only the _cdc companion table should be visible.
        # The DeltaLake files still exist on S3 for the seeding step to read from.
        is_cdc_only_initial = (
            cdc_write_mode is None
            and schema.sync_type == ExternalDataSchema.SyncType.CDC
            and schema.cdc_table_mode == "cdc_only"
        )

        if not is_cdc_only_initial:
            logger.debug("Validating schema and updating table")
            with POST_LOAD_DURATION_SECONDS.labels(operation="validate_schema").time():
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

        # After the initial snapshot load for a CDC schema, seed the companion _cdc table
        # with the snapshot rows as synthetic INSERT events.  Only fires when cdc_write_mode
        # is None (initial non-CDC load), NOT on every CDC consolidated streaming batch.
        should_seed = (
            cdc_write_mode is None
            and schema.sync_type == ExternalDataSchema.SyncType.CDC
            and schema.cdc_table_mode in ("cdc_only", "both")
            and delta_table_helper is not None
        )
        logger.info(
            "cdc_seed_check",
            should_seed=should_seed,
            cdc_write_mode=cdc_write_mode,
            sync_type=schema.sync_type,
            cdc_table_mode=schema.cdc_table_mode,
            has_delta_table_helper=delta_table_helper is not None,
        )
        if should_seed:
            logger.info("Seeding CDC companion table from snapshot")
            await _seed_cdc_companion_from_snapshot(
                schema=schema,
                job=job,
                source=source,
                snapshot_delta_table_helper=delta_table_helper,
                logger=logger,
            )
            logger.info("Finished seeding CDC companion table from snapshot")

    logger.debug("Syncing revenue analytics views if needed")
    await database_sync_to_async_pool(sync_revenue_analytics_views)(schema, source)
