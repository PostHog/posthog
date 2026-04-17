import datetime as dt
from collections.abc import Callable
from typing import Any, Literal

import s3fs
import pyarrow as pa
import structlog
import pyarrow.compute as pc
import posthoganalytics
from asgiref.sync import async_to_sync

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
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    DELTA_ROWS_WRITTEN_TOTAL,
    DELTA_WRITE_DURATION_SECONDS,
    IDEMPOTENCY_HIT_TOTAL,
    PARQUET_READ_DURATION_SECONDS,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3 import read_parquet
from posthog.temporal.data_imports.row_tracking import finish_row_tracking
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying
from posthog.utils import get_machine_id

from products.data_warehouse.backend.external_data_source.jobs import update_external_job_status
from products.data_warehouse.backend.models import ExternalDataJob
from products.data_warehouse.backend.models.table import DataWarehouseTable

logger = structlog.get_logger(__name__)


def _get_write_type(sync_type: SyncTypeLiteral) -> Literal["incremental", "full_refresh", "append"]:
    """Convert sync type to write type for DeltaTableHelper."""
    if sync_type in ("incremental", "cdc"):
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
        delta_schema = existing_delta_table.schema().to_arrow()
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
            logger.warning(
                "Found modified files during first sync, skipping partial data loading",
                modified_count=len(modified_files),
            )
            return

    if not new_file_uris:
        logger.debug("No new files to make queryable")
        return

    logger.debug(
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
    """Run post-load operations for a final batch whose data was already written to Delta Lake.

    The batch data (S3 read, partitioning, Delta Lake write) was already handled when
    the batch was first processed with is_final_batch=False. We only need to run
    post-load operations (compaction, S3 queryable folder prep, schema validation).

    All async operations are run within a single async_to_sync call to avoid
    event loop lifecycle issues with aiohttp/s3fs clients.
    """
    # Clear cached S3FileSystem instances to avoid reusing sessions bound to a
    # previously closed event loop (async_to_sync creates/destroys loops).
    s3fs.S3FileSystem.clear_instance_cache()

    async def _run() -> None:
        job = await ExternalDataJob.objects.prefetch_related("schema", "schema__source", "schema__table").aget(
            id=export_signal.job_id
        )
        schema = job.schema
        if schema is None:
            raise ValueError(f"ExternalDataJob {export_signal.job_id} has no schema")

        delta_table_helper = DeltaTableHelper(
            resource_name=export_signal.resource_name,
            job=job,
            logger=logger,
        )

        delta_table = await delta_table_helper.get_delta_table()
        if delta_table is None:
            logger.warning("no_delta_table_for_post_load", job_id=export_signal.job_id)
            return

        pa_table = read_parquet(export_signal.s3_path)
        internal_schema = HogQLSchema()
        internal_schema.add_pyarrow_schema(pa.schema(delta_table.schema().to_arrow()))
        internal_schema.add_pyarrow_table(pa_table)
        table_schema_dict = internal_schema.to_hogql_types()

        await run_post_load_operations(
            job=job,
            schema=schema,
            source=schema.source,
            delta_table_helper=delta_table_helper,
            row_count=export_signal.total_rows or 0,
            file_uris=delta_table.file_uris(),
            table_schema_dict=table_schema_dict,
            resource_name=export_signal.resource_name,
            logger=logger,
        )

        logger.debug("post_load_operations_complete_for_already_processed_batch")

    async_to_sync(_run)()


def _mark_job_completed(export_signal: ExportSignalMessage) -> None:
    job = update_external_job_status(
        job_id=export_signal.job_id,
        team_id=export_signal.team_id,
        status=ExternalDataJob.Status.COMPLETED,
        latest_error=None,
    )
    job.finished_at = dt.datetime.now(dt.UTC)
    job.save()

    async_to_sync(finish_row_tracking)(export_signal.team_id, export_signal.schema_id)

    logger.info(
        "job_marked_completed",
        job_id=export_signal.job_id,
        team_id=export_signal.team_id,
        schema_id=export_signal.schema_id,
    )


def _mark_job_failed(export_signal: ExportSignalMessage, error: Exception) -> None:
    # Short-circuit if the job is already FAILED: redelivered DLQ'd messages
    # (the retry state stays in Redis until its 72h TTL) would otherwise spam
    # status updates and latest_error rewrites for a terminal job.
    existing = ExternalDataJob.objects.filter(
        id=export_signal.job_id, team_id=export_signal.team_id, status=ExternalDataJob.Status.FAILED
    ).first()
    if existing is not None:
        logger.info(
            "job_already_marked_failed",
            job_id=export_signal.job_id,
            team_id=export_signal.team_id,
            schema_id=export_signal.schema_id,
        )
        return

    job = update_external_job_status(
        job_id=export_signal.job_id,
        team_id=export_signal.team_id,
        status=ExternalDataJob.Status.FAILED,
        latest_error=str(error),
    )
    job.finished_at = dt.datetime.now(dt.UTC)
    job.save()

    logger.info(
        "job_marked_failed",
        job_id=export_signal.job_id,
        team_id=export_signal.team_id,
        schema_id=export_signal.schema_id,
        error=str(error),
    )


def process_message(message: Any, progress_callback: Callable[[], None] | None = None) -> None:
    export_signal = ExportSignalMessage.from_dict(message)

    # Clear cached S3FileSystem instances to avoid reusing sessions bound to a
    # previously closed event loop (async_to_sync creates/destroys loops).
    s3fs.S3FileSystem.clear_instance_cache()

    try:
        team_id_str = str(export_signal.team_id)
        schema_id_str = str(export_signal.schema_id)

        already_processed = is_batch_already_processed(
            export_signal.team_id, export_signal.schema_id, export_signal.run_uuid, export_signal.batch_index
        )

        if already_processed and not export_signal.is_final_batch:
            IDEMPOTENCY_HIT_TOTAL.labels(team_id=team_id_str, schema_id=schema_id_str).inc()
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
            _mark_job_completed(export_signal)
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

        job = ExternalDataJob.objects.prefetch_related("schema", "schema__source", "schema__table").get(
            id=export_signal.job_id
        )
        schema = job.schema
        if schema is None:
            raise ValueError(f"ExternalDataJob {export_signal.job_id} has no schema")

        delta_table_helper = DeltaTableHelper(
            resource_name=export_signal.resource_name,
            job=job,
            logger=logger,
            is_first_sync=export_signal.is_first_ever_sync,
        )

        with PARQUET_READ_DURATION_SECONDS.time():
            pa_table = read_parquet(export_signal.s3_path)

        logger.debug(
            "parquet_file_read",
            s3_path=export_signal.s3_path,
            num_rows=pa_table.num_rows,
            num_columns=pa_table.num_columns,
            column_names=pa_table.column_names,
        )

        existing_delta_table = async_to_sync(delta_table_helper.get_delta_table)()

        pa_table = _apply_partitioning(export_signal, pa_table, existing_delta_table, schema)

        # Capture file URIs before write for partial data loading
        previous_file_uris = existing_delta_table.file_uris() if existing_delta_table else []

        primary_keys = export_signal.primary_keys
        cdc_write_mode = export_signal.cdc_write_mode

        # Cross-batch DELETE enrichment: fill data columns on DELETE rows from the
        # existing DeltaLake state. Batch-internal enrichment was already applied
        # in the extraction activity; this handles standalone DELETEs that arrive
        # in a batch with no preceding INSERT/UPDATE for the same PK.
        if cdc_write_mode is not None and primary_keys and existing_delta_table is not None:
            from posthog.temporal.data_imports.cdc.batcher import (
                CDC_OP_COLUMN,
                SCD2_VALID_TO_COLUMN,
                enrich_delete_rows,
            )

            if CDC_OP_COLUMN in pa_table.column_names:
                present_pks = [col for col in primary_keys if col in pa_table.column_names]
                if present_pks:
                    ops = pa_table.column(CDC_OP_COLUMN).to_pylist()
                    pk_arrays = [pa_table.column(col).to_pylist() for col in present_pks]
                    delete_key_set: set[tuple[Any, ...]] = set()
                    for i, op in enumerate(ops):
                        if op == "D":
                            delete_key_set.add(tuple(arr[i] for arr in pk_arrays))

                    if delete_key_set:
                        # Delta-rs: single-column IN avoids tuple filters (weak NULL semantics).
                        # For composite PKs that IN is a superset — narrow in PyArrow below.
                        first_pk = present_pks[0]
                        first_components = list({t[0] for t in delete_key_set})
                        existing_rows = existing_delta_table.to_pyarrow_table(
                            filters=[(first_pk, "in", first_components)]
                        )

                        # For composite PKs the IN filter is a superset — narrow to exact matches.
                        if len(present_pks) > 1 and existing_rows.num_rows > 0:
                            if all(col in existing_rows.column_names for col in present_pks):
                                ex_pk_arrays = [existing_rows.column(col).to_pylist() for col in present_pks]
                                match_indices = [
                                    j
                                    for j in range(existing_rows.num_rows)
                                    if tuple(arr[j] for arr in ex_pk_arrays) in delete_key_set
                                ]
                                existing_rows = existing_rows.take(match_indices)
                            else:
                                existing_rows = existing_rows.take([])

                        # For SCD2 tables, keep only "current" rows (valid_to IS NULL) so we
                        # enrich the DELETE with the most recent state rather than a historical one.
                        if (
                            cdc_write_mode == "scd2_append"
                            and existing_rows.num_rows > 0
                            and SCD2_VALID_TO_COLUMN in existing_rows.column_names
                        ):
                            existing_rows = existing_rows.filter(pc.is_null(existing_rows.column(SCD2_VALID_TO_COLUMN)))

                        pa_table = enrich_delete_rows(pa_table, primary_keys, existing_rows)

        if cdc_write_mode == "scd2_append":
            logger.debug(
                "writing_scd2_to_delta_lake",
                primary_keys=primary_keys,
                batch_index=export_signal.batch_index,
            )

            with DELTA_WRITE_DURATION_SECONDS.labels(
                team_id=team_id_str, schema_id=schema_id_str, write_type="scd2_append"
            ).time():
                delta_table = async_to_sync(delta_table_helper.write_scd2_to_deltalake)(
                    data=pa_table,
                    primary_keys=primary_keys or [],
                )
        else:
            write_type = _get_write_type(export_signal.sync_type)

            # First batch should overwrite the table, but only if not resuming
            should_overwrite_table = export_signal.batch_index == 0 and not export_signal.is_resume

            logger.debug(
                "writing_to_delta_lake",
                write_type=write_type,
                should_overwrite_table=should_overwrite_table,
                primary_keys=primary_keys,
                batch_index=export_signal.batch_index,
            )

            with DELTA_WRITE_DURATION_SECONDS.labels(
                team_id=team_id_str, schema_id=schema_id_str, write_type=write_type
            ).time():
                delta_table = async_to_sync(delta_table_helper.write_to_deltalake)(
                    data=pa_table,
                    write_type=write_type,
                    should_overwrite_table=should_overwrite_table,
                    primary_keys=primary_keys,
                    progress_callback=progress_callback,
                )

        DELTA_ROWS_WRITTEN_TOTAL.labels(team_id=team_id_str, schema_id=schema_id_str).inc(pa_table.num_rows)

        internal_schema = HogQLSchema()
        # Build from the Delta table schema first to cover all columns from
        # all batches, then overlay the current batch for JSON detection.
        internal_schema.add_pyarrow_schema(pa.schema(delta_table.schema().to_arrow()))  # type: ignore[arg-type]  # arro3 Schema implements the Arrow C Data Interface
        internal_schema.add_pyarrow_table(pa_table)

        logger.debug(
            "batch_written_to_delta_lake",
            batch_index=export_signal.batch_index,
            file_count=len(delta_table.file_uris()),
        )

        # Handle partial data loading for first-ever sync
        async_to_sync(_handle_partial_data_loading)(
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
                cdc_write_mode=export_signal.cdc_write_mode,
                cdc_table_mode=export_signal.cdc_table_mode,
                sync_type=export_signal.sync_type,
                schema_sync_type=schema.sync_type,
                schema_cdc_table_mode=schema.cdc_table_mode,
                resource_name=export_signal.resource_name,
            )

            async_to_sync(run_post_load_operations)(
                job=job,
                schema=schema,
                source=schema.source,
                delta_table_helper=delta_table_helper,
                row_count=export_signal.total_rows or 0,
                file_uris=delta_table.file_uris(),
                table_schema_dict=internal_schema.to_hogql_types(),
                resource_name=export_signal.resource_name,
                logger=logger,
                cdc_table_mode=export_signal.cdc_table_mode,
                cdc_write_mode=export_signal.cdc_write_mode,
            )

            _mark_job_completed(export_signal)

            logger.debug("post_load_operations_complete")

        mark_batch_as_processed(
            export_signal.team_id, export_signal.schema_id, export_signal.run_uuid, export_signal.batch_index
        )

        if export_signal.is_final_batch:
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="warehouse_v3_load_completed",
                properties={
                    "team_id": export_signal.team_id,
                    "schema_id": export_signal.schema_id,
                    "source_id": export_signal.source_id,
                    "resource_name": export_signal.resource_name,
                    "sync_type": export_signal.sync_type,
                    "total_batches": export_signal.total_batches,
                    "total_rows": export_signal.total_rows,
                },
            )
    except Exception as e:
        posthoganalytics.capture(
            distinct_id=get_machine_id(),
            event="warehouse_v3_load_failed",
            properties={
                "team_id": export_signal.team_id,
                "schema_id": export_signal.schema_id,
                "source_id": export_signal.source_id,
                "resource_name": export_signal.resource_name,
                "sync_type": export_signal.sync_type,
                "batch_index": export_signal.batch_index,
                "error_type": type(e).__name__,
                "error_message": str(e)[:1000],
            },
        )
        raise
