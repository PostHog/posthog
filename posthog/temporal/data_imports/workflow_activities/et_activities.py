import gc
import uuid
import datetime as dt
import dataclasses
from typing import Any, NoReturn

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Prefetch

import pyarrow as pa
import posthoganalytics
from redis import Redis
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.pipeline.temp_storage import TempStorageWriter
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    _append_debug_column_to_pyarrows_table,
    _evolve_pyarrow_schema,
    _handle_null_columns_with_definitions,
    normalize_table_column_names,
    setup_partitioning,
)
from posthog.temporal.data_imports.util import NonRetryableException

LOGGER = get_logger(__name__)


def _get_redis() -> Redis | None:
    """Get Redis client for non-retryable error tracking."""
    try:
        from posthog.redis import get_client as get_redis_client

        return get_redis_client()
    except Exception:
        return None


def _non_retryable_errors_key(team_id: int, source_id: str, job_id: str) -> str:
    """Generate Redis key for tracking non-retryable error attempts."""
    return f"posthog:data_warehouse:non_retryable_errors:{team_id}:{source_id}:{job_id}"


def _handle_non_retryable_error(
    team_id: int, source_id: str, job_id: str, error_msg: str, logger, error: Exception
) -> NoReturn:
    """Track non-retryable errors in Redis, allow 3 attempts before giving up."""
    redis_client = _get_redis()
    if redis_client is None:
        logger.debug(f"Failed to get Redis client for non-retryable error tracking. error={error_msg}")
        raise NonRetryableException() from error

    retry_key = _non_retryable_errors_key(team_id, source_id, job_id)
    attempts = redis_client.incr(retry_key)

    if attempts <= 3:
        redis_client.expire(retry_key, 86400)  # Expire after 24 hours
        logger.debug(f"Non-retryable error attempt {attempts}/3, retrying. error={error_msg}")
        raise error  # Re-raise original error to trigger retry

    logger.debug(f"Non-retryable error after {attempts} runs, giving up. error={error_msg}")
    raise NonRetryableException() from error


def _trim_source_job_inputs(source) -> None:
    """Strip whitespace from config values to prevent user input errors."""
    if not source.job_inputs:
        return

    did_update_inputs = False
    for key, value in source.job_inputs.items():
        if isinstance(value, str):
            if value.startswith(" ") or value.endswith(" "):
                source.job_inputs[key] = value.strip()
                did_update_inputs = True

    if did_update_inputs:
        source.save()


def _report_heartbeat_timeout(team_id: int, source_id: str, schema_id: str, job_id: str, logger) -> None:
    """Report heartbeat timeout analytics if detected."""
    try:
        info = activity.info()
        heartbeat_timeout = info.heartbeat_timeout
        current_attempt_scheduled_time = info.current_attempt_scheduled_time

        if not heartbeat_timeout or not current_attempt_scheduled_time:
            return

        if info.attempt < 2:
            return  # First attempt, no timeout to report

        heartbeat_details = info.heartbeat_details
        if not isinstance(heartbeat_details, tuple | list) or len(heartbeat_details) < 1:
            return

        last_heartbeat = heartbeat_details[-1]
        if not isinstance(last_heartbeat, dict):
            return

        last_heartbeat_host = last_heartbeat.get("host")
        last_heartbeat_timestamp = last_heartbeat.get("ts")

        if last_heartbeat_host is None or last_heartbeat_timestamp is None:
            return

        try:
            last_heartbeat_timestamp = float(last_heartbeat_timestamp)
        except (TypeError, ValueError):
            return

        gap_between_beats = current_attempt_scheduled_time.timestamp() - last_heartbeat_timestamp
        if gap_between_beats > heartbeat_timeout.total_seconds():
            logger.debug(
                "Heartbeat timeout detected - likely pod OOM or restart",
                last_heartbeat_host=last_heartbeat_host,
                gap_between_beats=gap_between_beats,
            )
            posthoganalytics.capture(
                "dwh_pod_heartbeat_timeout",
                distinct_id=None,
                properties={
                    "team_id": team_id,
                    "schema_id": schema_id,
                    "source_id": source_id,
                    "run_id": job_id,
                    "host": last_heartbeat_host,
                    "gap_between_beats": gap_between_beats,
                    "heartbeat_timeout_seconds": heartbeat_timeout.total_seconds(),
                    "task_queue": info.task_queue,
                    "workflow_id": info.workflow_id,
                    "workflow_run_id": info.workflow_run_id,
                    "workflow_type": info.workflow_type,
                    "attempt": info.attempt,
                },
            )
    except Exception as e:
        logger.debug(f"Error while reporting heartbeat timeout: {e}")


@dataclasses.dataclass
class UpdateETTrackingInputs:
    job_id: str
    et_workflow_id: str | None = None
    l_workflow_id: str | None = None
    temp_s3_prefix: str | None = None
    manifest_path: str | None = None
    et_started_at: bool = False
    et_finished_at: bool = False
    l_started_at: bool = False
    l_finished_at: bool = False
    et_rows_extracted: int | None = None
    l_rows_loaded: int | None = None
    pipeline_version: str | None = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"job_id": self.job_id}


@activity.defn
def update_et_tracking_activity(inputs: UpdateETTrackingInputs) -> None:
    """Update ET+L tracking fields on the job record."""
    from products.data_warehouse.backend.models import ExternalDataJob

    close_old_connections()

    job = ExternalDataJob.objects.get(id=inputs.job_id)

    if inputs.et_workflow_id is not None:
        job.et_workflow_id = inputs.et_workflow_id
    if inputs.l_workflow_id is not None:
        job.l_workflow_id = inputs.l_workflow_id
    if inputs.temp_s3_prefix is not None:
        job.temp_s3_prefix = inputs.temp_s3_prefix
    if inputs.manifest_path is not None:
        job.manifest_path = inputs.manifest_path
    if inputs.et_started_at:
        job.et_started_at = dt.datetime.now(dt.UTC)
    if inputs.et_finished_at:
        job.et_finished_at = dt.datetime.now(dt.UTC)
    if inputs.l_started_at:
        job.l_started_at = dt.datetime.now(dt.UTC)
    if inputs.l_finished_at:
        job.l_finished_at = dt.datetime.now(dt.UTC)
    if inputs.et_rows_extracted is not None:
        job.et_rows_extracted = inputs.et_rows_extracted
    if inputs.l_rows_loaded is not None:
        job.l_rows_loaded = inputs.l_rows_loaded
    if inputs.pipeline_version is not None:
        job.pipeline_version = inputs.pipeline_version

    job.save()


@dataclasses.dataclass
class CreateJobBatchInputs:
    job_id: str
    batch_number: int
    parquet_path: str
    row_count: int | None = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "batch_number": self.batch_number}


@activity.defn
def create_job_batch_activity(inputs: CreateJobBatchInputs) -> str:
    """Create a batch record for tracking parquet files."""
    from products.data_warehouse.backend.models import ExternalDataJobBatch

    close_old_connections()

    batch = ExternalDataJobBatch.objects.create(
        job_id=inputs.job_id,
        batch_number=inputs.batch_number,
        parquet_path=inputs.parquet_path,
        row_count=inputs.row_count,
    )

    return str(batch.id)


@dataclasses.dataclass
class UpdateJobBatchLoadedInputs:
    job_id: str
    batch_number: int
    parquet_path: str | None = None
    row_count: int | None = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "batch_number": self.batch_number}


@activity.defn
def update_job_batch_loaded_activity(inputs: UpdateJobBatchLoadedInputs) -> None:
    """Create or update a batch record, marking it as loaded."""
    from products.data_warehouse.backend.models import ExternalDataJobBatch

    close_old_connections()

    # Create batch record if it doesn't exist, update loaded_at either way
    ExternalDataJobBatch.objects.update_or_create(
        job_id=inputs.job_id,
        batch_number=inputs.batch_number,
        defaults={
            "parquet_path": inputs.parquet_path or "",
            "row_count": inputs.row_count,
            "loaded_at": dt.datetime.now(dt.UTC),
        },
    )


@dataclasses.dataclass
class StartLoadWorkflowInputs:
    workflow_id: str
    team_id: int
    source_id: str
    schema_id: str
    job_id: str
    source_type: str | None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "team_id": self.team_id,
            "source_id": self.source_id,
            "schema_id": self.schema_id,
            "job_id": self.job_id,
            "source_type": self.source_type,
        }


@dataclasses.dataclass
class ExtractBatchInputs:
    team_id: int
    source_id: uuid.UUID
    schema_id: uuid.UUID
    job_id: str
    temp_s3_prefix: str | None
    reset_pipeline: bool = False
    load_workflow_id: str | None = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "source_id": str(self.source_id),
            "schema_id": str(self.schema_id),
            "job_id": self.job_id,
            "reset_pipeline": self.reset_pipeline,
        }


@dataclasses.dataclass
class ExtractBatchResult:
    """Result from extract_and_transform_batch_activity."""

    is_done: bool
    batch_path: str | None
    batch_number: int
    row_count: int
    schema_path: str | None
    temp_s3_prefix: str
    manifest_path: str | None


@activity.defn
async def start_load_workflow_activity(inputs: StartLoadWorkflowInputs) -> None:
    """Start the Load workflow independently."""
    from posthog.temporal.common.client import async_connect
    from posthog.temporal.data_imports.load_data_job import LoadDataJobInputs, LoadDataJobWorkflow

    logger = LOGGER.bind(team_id=inputs.team_id)
    logger.debug(f"Starting Load workflow with ID: {inputs.workflow_id}")

    client = await async_connect()

    await client.start_workflow(
        LoadDataJobWorkflow.run,
        LoadDataJobInputs(
            team_id=inputs.team_id,
            source_id=inputs.source_id,
            schema_id=inputs.schema_id,
            job_id=inputs.job_id,
            source_type=inputs.source_type,
        ),
        id=inputs.workflow_id,
        task_queue=settings.DATA_WAREHOUSE_LOAD_TASK_QUEUE,
    )

    logger.debug(f"Load workflow started: {inputs.workflow_id}")


@activity.defn
async def extract_and_transform_batch_activity(inputs: ExtractBatchInputs) -> ExtractBatchResult:
    """
    Extract and transform data in batches, signaling L workflow after each batch.
    """
    import time
    import asyncio

    from asgiref.sync import sync_to_async

    from posthog.temporal.common.client import async_connect
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.shutdown import ShutdownMonitor
    from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
    from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
    from posthog.temporal.data_imports.pipelines.pipeline.signals import BatchReadySignal, ETCompleteSignal
    from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
    from posthog.temporal.data_imports.sources import SourceRegistry
    from posthog.temporal.data_imports.sources.common.base import ResumableSource
    from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager

    from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema
    from products.data_warehouse.backend.models.external_data_schema import process_incremental_value
    from products.data_warehouse.backend.types import ExternalDataSourceType

    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await sync_to_async(close_old_connections)()

    logger.debug("Starting extract_and_transform_batch_activity")

    # Report any heartbeat timeout from previous attempt
    _report_heartbeat_timeout(inputs.team_id, str(inputs.source_id), str(inputs.schema_id), inputs.job_id, logger)

    # Get Temporal client for signaling L workflow
    load_handle = None
    if inputs.load_workflow_id:
        client = await async_connect()
        load_handle = client.get_workflow_handle(inputs.load_workflow_id)
        logger.debug(f"Will signal L workflow: {inputs.load_workflow_id}")

    # Get job and schema
    @sync_to_async
    def get_job_and_schema():
        job = ExternalDataJob.objects.prefetch_related(
            "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
        ).get(id=inputs.job_id)
        schema = job.schema
        assert schema is not None
        _trim_source_job_inputs(job.pipeline)
        chunk_size_override = schema.chunk_size_override
        return job, schema, chunk_size_override

    job, schema, chunk_size_override = await get_job_and_schema()

    source_type = ExternalDataSourceType(job.pipeline.source_type)

    # Determine if we should reset the pipeline
    reset_pipeline = inputs.reset_pipeline or schema.sync_type_config.get("reset_pipeline", False) is True
    logger.debug(f"reset_pipeline = {reset_pipeline}")

    # If reset_pipeline is True, ignore the incremental cursor to fetch all data
    if reset_pipeline:
        processed_incremental_last_value = None
        logger.debug("Ignoring incremental_field_last_value due to reset_pipeline=True")
    else:
        processed_incremental_last_value = process_incremental_value(
            schema.sync_type_config.get("incremental_field_last_value"),
            schema.sync_type_config.get("incremental_field_type"),
        )

    processed_incremental_earliest_value = process_incremental_value(
        schema.incremental_field_earliest_value,
        schema.incremental_field_type,
    )

    source_inputs = SourceInputs(
        schema_name=schema.name,
        schema_id=str(schema.id),
        team_id=inputs.team_id,
        should_use_incremental_field=schema.should_use_incremental_field,
        incremental_field=schema.incremental_field if schema.should_use_incremental_field else None,
        incremental_field_type=schema.incremental_field_type if schema.should_use_incremental_field else None,
        db_incremental_field_last_value=processed_incremental_last_value
        if schema.should_use_incremental_field
        else None,
        db_incremental_field_earliest_value=processed_incremental_earliest_value
        if schema.should_use_incremental_field
        else None,
        logger=logger,
        job_id=inputs.job_id,
        chunk_size_override=chunk_size_override,
    )

    new_source = SourceRegistry.get_source(source_type)
    config = new_source.parse_config(job.pipeline.job_inputs)

    resumable_source_manager: ResumableSourceManager | None = None
    if isinstance(new_source, ResumableSource):
        resumable_source_manager = new_source.get_resumable_source_manager(source_inputs)
        source = await sync_to_async(new_source.source_for_pipeline)(config, resumable_source_manager, source_inputs)
    else:
        source = await sync_to_async(new_source.source_for_pipeline)(config, source_inputs)

    temp_writer = TempStorageWriter(
        team_id=inputs.team_id,
        source_id=str(inputs.source_id),
        schema_id=str(inputs.schema_id),
        job_id=inputs.job_id,
        table_name=source.name,
    )

    if inputs.temp_s3_prefix:
        temp_writer.temp_s3_prefix = inputs.temp_s3_prefix
        temp_writer.data_prefix = f"{inputs.temp_s3_prefix}/data"

    batcher = Batcher(logger)
    hogql_schema = HogQLSchema()
    load_id = int(time.time_ns())

    sync_type = "full_refresh"
    if schema.is_incremental:
        sync_type = "incremental"
    elif schema.is_append:
        sync_type = "append"

    batch_number = 0
    total_rows = 0

    # Memory pool for cleanup
    pa_memory_pool = pa.default_memory_pool()

    # Queue for passing batch info from sync extraction to async signaling
    batch_queue: asyncio.Queue[BatchReadySignal | None] = asyncio.Queue()

    # Capture the event loop before starting the thread
    main_loop = asyncio.get_running_loop()

    async def signal_batches():
        """Async task that sends signals for completed batches."""
        if not load_handle:
            return

        while True:
            batch_signal = await batch_queue.get()
            if batch_signal is None:  # Sentinel to stop
                break
            await load_handle.signal("batch_ready", batch_signal)
            logger.debug(f"Signaled L workflow for batch {batch_signal.batch_number}")

    def run_extraction():
        """Sync function that extracts data and queues batches for signaling."""
        nonlocal batch_number, total_rows

        with ShutdownMonitor() as shutdown_monitor:
            # Extract all data and write batches
            for item in source.items():
                batcher.batch(item)

                if batcher.should_yield():
                    pa_table = batcher.get_table()

                    # Transform
                    pa_table = _transform_batch(pa_table, schema, source, load_id, logger)
                    hogql_schema.add_pyarrow_table(pa_table)

                    # Write to temp storage
                    batch_path = temp_writer.write_batch(pa_table)
                    row_count = pa_table.num_rows
                    total_rows += row_count

                    logger.debug(f"Wrote batch {batch_number} with {row_count} rows to {batch_path}")

                    # Queue signal for L workflow
                    if load_handle:
                        asyncio.run_coroutine_threadsafe(
                            batch_queue.put(
                                BatchReadySignal(
                                    batch_path=batch_path,
                                    batch_number=batch_number,
                                    schema_path=temp_writer.get_schema_path() or "",
                                    row_count=row_count,
                                    primary_keys=source.primary_keys,
                                    sync_type=sync_type,
                                )
                            ),
                            main_loop,
                        )

                    batch_number += 1

                    # Memory cleanup after each batch
                    del pa_table
                    pa_memory_pool.release_unused()
                    gc.collect()  # It may not be necessary, but is a best-effort memory release

                    # Check for shutdown
                    shutdown_monitor.raise_if_is_worker_shutdown()

            # Handle remaining data in batcher
            if batcher.should_yield(include_incomplete_chunk=True):
                pa_table = batcher.get_table()
                pa_table = _transform_batch(pa_table, schema, source, load_id, logger)
                hogql_schema.add_pyarrow_table(pa_table)

                batch_path = temp_writer.write_batch(pa_table)
                row_count = pa_table.num_rows
                total_rows += row_count

                logger.debug(f"Wrote final batch {batch_number} with {row_count} rows")

                # Queue signal for final batch
                if load_handle:
                    asyncio.run_coroutine_threadsafe(
                        batch_queue.put(
                            BatchReadySignal(
                                batch_path=batch_path,
                                batch_number=batch_number,
                                schema_path=temp_writer.get_schema_path() or "",
                                row_count=row_count,
                                primary_keys=source.primary_keys,
                                sync_type=sync_type,
                            )
                        ),
                        main_loop,
                    )

                batch_number += 1

                # Memory cleanup
                del pa_table
                pa_memory_pool.release_unused()
                gc.collect()  # It may not be necessary, but is a best-effort memory release

        # Signal end of batches
        if load_handle:
            asyncio.run_coroutine_threadsafe(batch_queue.put(None), main_loop)

    try:
        async with Heartbeater(factor=30):
            # Start the signal sender task
            signal_task = asyncio.create_task(signal_batches())

            await asyncio.to_thread(run_extraction)

            if load_handle:
                await signal_task

    except Exception as e:
        error_msg = str(e)
        non_retryable_errors = new_source.get_non_retryable_errors()
        is_non_retryable_error = any(
            non_retryable_error in error_msg for non_retryable_error in non_retryable_errors.keys()
        )
        if is_non_retryable_error:
            _handle_non_retryable_error(inputs.team_id, str(inputs.source_id), inputs.job_id, error_msg, logger, e)
        raise
    finally:
        # Final memory cleanup
        pa_memory_pool.release_unused()
        gc.collect()

    # Finalize and create manifest
    manifest = temp_writer.finalize(
        primary_keys=source.primary_keys,
        partition_count=source.partition_count,
        partition_keys=source.partition_keys,
        partition_mode=source.partition_mode,
        sync_type=sync_type,
        incremental_field=schema.incremental_field if schema.should_use_incremental_field else None,
        incremental_field_last_value=None,  # Will be updated during load
        incremental_field_earliest_value=None,
        run_id=inputs.job_id,
        hogql_schema=hogql_schema.to_hogql_types(),
    )

    # Signal ET complete to L workflow
    if load_handle:
        await load_handle.signal(
            "et_complete",
            ETCompleteSignal(
                manifest_path=manifest.get_manifest_path(),
                total_batches=batch_number,
                total_rows=total_rows,
            ),
        )
        logger.debug(f"Signaled ET complete: {batch_number} batches, {total_rows} rows")

    logger.debug(f"ET complete: {batch_number} batches, {total_rows} total rows")

    # Clear the reset_pipeline flag from sync_type_config after successful extraction
    if reset_pipeline:
        await sync_to_async(schema.update_sync_type_config_for_reset_pipeline)()
        logger.debug("Cleared reset_pipeline flag from sync_type_config")

    return ExtractBatchResult(
        is_done=True,
        batch_path=None,
        batch_number=batch_number,
        row_count=total_rows,
        schema_path=temp_writer.get_schema_path(),
        temp_s3_prefix=temp_writer.temp_s3_prefix,
        manifest_path=manifest.get_manifest_path(),
    )


def _transform_batch(
    pa_table: pa.Table,
    schema,
    source,
    load_id: int,
    logger,
) -> pa.Table:
    """Apply transformations to a PyArrow table batch."""
    # Add debug column
    pa_table = _append_debug_column_to_pyarrows_table(pa_table, load_id)

    # Normalize column names
    pa_table = normalize_table_column_names(pa_table)

    # Setup partitioning (adds _ph_partition_key if configured)
    pa_table = setup_partitioning(pa_table, None, schema, source, logger)

    # Evolve schema (handle type conversions)
    pa_table = _evolve_pyarrow_schema(pa_table, None)

    # Handle null columns with definitions
    pa_table = _handle_null_columns_with_definitions(pa_table, source)

    return pa_table
