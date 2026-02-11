from typing import Any, Literal

import structlog

from posthog.temporal.data_imports.pipelines.common.load import run_post_load_operations, supports_partial_data_loading
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline.utils import append_partition_key_to_table
from posthog.temporal.data_imports.pipelines.pipeline_sync import validate_schema_and_update_table
from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.common import ExportSignalMessage, SyncTypeLiteral
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency import (
    is_batch_already_processed,
    mark_batch_as_processed,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3 import read_parquet
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying

from products.data_warehouse.backend.models import ExternalDataJob
from products.data_warehouse.backend.models.table import DataWarehouseTable

logger = structlog.get_logger(__name__)


def _get_write_type(sync_type: SyncTypeLiteral) -> Literal["incremental", "full_refresh", "append"]:
    """Convert sync type to write type for DeltaTableHelper."""
    if sync_type == "incremental":
        return "incremental"
    elif sync_type == "append":
        return "append"
    return "full_refresh"


def _apply_partitioning(
    export_signal: ExportSignalMessage, pa_table: Any, existing_delta_table: Any, schema: Any
) -> Any:
    """Apply partitioning to the table if configured."""
    partition_keys = export_signal.partition_keys

    if not partition_keys:
        logger.debug("No partition keys, skipping partitioning")
        return pa_table

    if existing_delta_table:
        delta_schema = existing_delta_table.schema().to_pyarrow()
        if PARTITION_KEY not in delta_schema.names:
            logger.debug("Delta table already exists without partitioning, skipping partitioning")
            return pa_table

    partition_result = append_partition_key_to_table(
        table=pa_table,
        partition_count=export_signal.partition_count,
        partition_size=export_signal.partition_size,
        partition_keys=partition_keys,
        partition_mode=export_signal.partition_mode,
        partition_format=export_signal.partition_format,
        logger=logger,
    )

    if partition_result is not None:
        pa_table, partition_mode, partition_format, updated_partition_keys = partition_result

        if (
            not schema.partitioning_enabled
            or schema.partition_mode != partition_mode
            or schema.partition_format != partition_format
            or schema.partitioning_keys != updated_partition_keys
        ):
            logger.debug(
                f"Setting partitioning_enabled on schema with: partition_keys={partition_keys}. partition_count={export_signal.partition_count}. partition_mode={partition_mode}. partition_format={partition_format}"
            )
            schema.set_partitioning_enabled(
                updated_partition_keys,
                export_signal.partition_count,
                export_signal.partition_size,
                partition_mode,
                partition_format,
            )

    return pa_table


async def _handle_partial_data_loading(
    export_signal: ExportSignalMessage,
    job: ExternalDataJob,
    schema: Any,
    delta_table: Any,
    previous_file_uris: list[str],
    internal_schema: HogQLSchema,
) -> None:
    """Make data available for querying during first-ever sync for Stripe sources."""
    if not export_signal.is_first_ever_sync:
        return

    if not supports_partial_data_loading(schema):
        return

    current_file_uris = delta_table.file_uris()

    if export_signal.batch_index == 0:
        new_file_uris = current_file_uris
    else:
        new_file_uris = list(set(current_file_uris) - set(previous_file_uris))
        modified_files = set(previous_file_uris) - set(current_file_uris)
        if modified_files:
            await logger.awarning(
                "Found modified files during first sync, skipping partial data loading",
                modified_count=len(modified_files),
            )
            return

    if not new_file_uris:
        await logger.adebug("No new files to make queryable")
        return

    await logger.adebug(
        "partial_data_loading",
        batch_index=export_signal.batch_index,
        new_file_count=len(new_file_uris),
        cumulative_row_count=export_signal.cumulative_row_count,
    )

    queryable_folder = await prepare_s3_files_for_querying(
        folder_path=job.folder_path(),
        table_name=export_signal.resource_name,
        file_uris=new_file_uris,
        delete_existing=(export_signal.batch_index == 0),
        use_timestamped_folders=False,
        logger=logger,
    )

    await validate_schema_and_update_table(
        run_id=str(job.id),
        team_id=job.team_id,
        schema_id=schema.id,
        table_schema_dict=internal_schema.to_hogql_types(),
        row_count=export_signal.cumulative_row_count,
        queryable_folder=queryable_folder,
        table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
    )

    logger.debug("partial_data_loading_complete", queryable_folder=queryable_folder)


def _run_post_load_for_already_processed_batch(export_signal: ExportSignalMessage) -> None:
    """Run post-load operations for a final batch whose data was already written to Delta Lake."""
    job = ExternalDataJob.objects.prefetch_related("schema", "schema__source").get(id=export_signal.job_id)
    schema = job.schema
    assert schema is not None

    delta_table_helper = DeltaTableHelper(
        resource_name=export_signal.resource_name,
        job=job,
        logger=logger,
    )

    delta_table = delta_table_helper.get_delta_table()
    if delta_table is None:
        logger.warning("no_delta_table_for_post_load", job_id=export_signal.job_id)
        return

    pa_table = read_parquet(export_signal.s3_path)
    internal_schema = HogQLSchema()
    internal_schema.add_pyarrow_table(pa_table)

    run_post_load_operations(
        job=job,
        schema=schema,
        source=schema.source,
        delta_table_helper=delta_table_helper,
        row_count=export_signal.total_rows or 0,
        file_uris=delta_table.file_uris(),
        table_schema_dict=internal_schema.to_hogql_types(),
        resource_name=export_signal.resource_name,
        logger=logger,
    )

    logger.debug("post_load_operations_complete_for_already_processed_batch")


def process_message(message: Any) -> None:
    export_signal = ExportSignalMessage.from_dict(message.value)

    already_processed = is_batch_already_processed(
        export_signal.team_id, export_signal.schema_id, export_signal.run_uuid, export_signal.batch_index
    )

    if already_processed and not export_signal.is_final_batch:
        logger.info(
            "batch_already_processed",
            team_id=export_signal.team_id,
            schema_id=export_signal.schema_id,
            run_uuid=export_signal.run_uuid,
            batch_index=export_signal.batch_index,
        )
        return

    if already_processed and export_signal.is_final_batch:
        logger.info(
            "batch_already_processed_running_post_load",
            team_id=export_signal.team_id,
            schema_id=export_signal.schema_id,
            run_uuid=export_signal.run_uuid,
            batch_index=export_signal.batch_index,
        )
        _run_post_load_for_already_processed_batch(export_signal)
        return

    logger.debug(
        "message_received",
        team_id=export_signal.team_id,
        schema_id=export_signal.schema_id,
        resource_name=export_signal.resource_name,
        batch_index=export_signal.batch_index,
        is_final_batch=export_signal.is_final_batch,
        row_count=export_signal.row_count,
        s3_path=export_signal.s3_path,
        sync_type=export_signal.sync_type,
    )

    job = ExternalDataJob.objects.prefetch_related("schema", "schema__source").get(id=export_signal.job_id)
    schema = job.schema
    assert schema is not None

    delta_table_helper = DeltaTableHelper(
        resource_name=export_signal.resource_name,
        job=job,
        logger=logger,
    )

    pa_table = read_parquet(export_signal.s3_path)

    logger.debug(
        "parquet_file_read",
        s3_path=export_signal.s3_path,
        num_rows=pa_table.num_rows,
        num_columns=pa_table.num_columns,
        column_names=pa_table.column_names,
    )

    existing_delta_table = delta_table_helper.get_delta_table()

    pa_table = _apply_partitioning(export_signal, pa_table, existing_delta_table, schema)

    # Capture file URIs before write for partial data loading
    previous_file_uris = existing_delta_table.file_uris() if existing_delta_table else []

    write_type = _get_write_type(export_signal.sync_type)
    primary_keys = export_signal.primary_keys

    # First batch should overwrite the table, but only if not resuming
    should_overwrite_table = export_signal.batch_index == 0 and not export_signal.is_resume

    logger.debug(
        "writing_to_delta_lake",
        write_type=write_type,
        should_overwrite_table=should_overwrite_table,
        primary_keys=primary_keys,
        batch_index=export_signal.batch_index,
    )

    delta_table = delta_table_helper.write_to_deltalake(
        data=pa_table,
        write_type=write_type,
        should_overwrite_table=should_overwrite_table,
        primary_keys=primary_keys,
    )

    internal_schema = HogQLSchema()
    internal_schema.add_pyarrow_table(pa_table)

    logger.debug(
        "batch_written_to_delta_lake",
        batch_index=export_signal.batch_index,
        file_count=len(delta_table.file_uris()),
    )

    # Handle partial data loading for first-ever sync
    _handle_partial_data_loading(
        export_signal=export_signal,
        job=job,
        schema=schema,
        delta_table=delta_table,
        previous_file_uris=previous_file_uris,
        internal_schema=internal_schema,
    )

    if export_signal.is_final_batch:
        logger.debug(
            "final_batch_received",
            total_batches=export_signal.total_batches,
            total_rows=export_signal.total_rows,
        )

        run_post_load_operations(
            job=job,
            schema=schema,
            source=schema.source,
            delta_table_helper=delta_table_helper,
            row_count=export_signal.total_rows or 0,
            file_uris=delta_table.file_uris(),
            table_schema_dict=internal_schema.to_hogql_types(),
            resource_name=export_signal.resource_name,
            logger=logger,
        )

        logger.debug("post_load_operations_complete")

    mark_batch_as_processed(
        export_signal.team_id, export_signal.schema_id, export_signal.run_uuid, export_signal.batch_index
    )
