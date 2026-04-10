import time
import asyncio
from typing import Any, Generic

import pyarrow as pa
import posthoganalytics
from structlog.types import FilteringBoundLogger
from temporalio import activity

from posthog.models import DataWarehouseTable
from posthog.temporal.common.shutdown import ShutdownMonitor
from posthog.temporal.data_imports.pipelines.common.extract import (
    cdp_producer_clear_chunks,
    cleanup_memory,
    finalize_desc_sort_incremental_value,
    handle_reset_or_full_refresh,
    reset_rows_synced_if_needed,
    setup_row_tracking_with_billing_check,
    should_check_shutdown,
    update_incremental_field_values,
    update_row_tracking_after_batch,
    validate_incremental_sync,
    write_chunk_for_cdp_producer,
)
from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.cdp_producer import CDPProducer
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline.pipeline import async_iterate
from posthog.temporal.data_imports.pipelines.pipeline.typings import PipelineResult, ResumableData, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    _append_debug_column_to_pyarrows_table,
    _evolve_pyarrow_schema,
    _handle_null_columns_with_definitions,
    normalize_table_column_names,
)
from posthog.temporal.data_imports.pipelines.pipeline_sync import set_initial_sync_complete
from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka import KafkaBatchProducer, SyncTypeLiteral
from posthog.temporal.data_imports.pipelines.pipeline_v3.metrics import (
    get_batches_produced_metric,
    get_pipeline_run_duration_metric,
    get_rows_extracted_metric,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult, S3BatchWriter
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3.writer import ParquetCompression
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.utils import get_machine_id

from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema
from products.data_warehouse.backend.models.external_data_schema import process_incremental_value
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

PARQUET_COMPRESSION: ParquetCompression = "zstd"


class PipelineV3(Generic[ResumableData]):
    _resource: SourceResponse
    _resource_name: str
    _job: ExternalDataJob
    _source: ExternalDataSource
    _schema: ExternalDataSchema
    _table: DataWarehouseTable | None
    _logger: FilteringBoundLogger
    _is_incremental: bool
    _reset_pipeline: bool
    _delta_table_helper: DeltaTableHelper
    _resumable_source_manager: ResumableSourceManager[ResumableData] | None
    _internal_schema: HogQLSchema
    _cdp_producer: CDPProducer
    _batcher: Batcher
    _load_id: int
    _s3_batch_writer: S3BatchWriter
    _kafka_producer: KafkaBatchProducer
    _accumulated_pa_schema: pa.Schema | None
    _batch_results: list[BatchWriteResult]

    def __init__(
        self,
        source_response: SourceResponse,
        logger: FilteringBoundLogger,
        job_id: str,
        reset_pipeline: bool,
        shutdown_monitor: ShutdownMonitor,
        job: ExternalDataJob,
        schema: ExternalDataSchema,
        source: ExternalDataSource,
        table: DataWarehouseTable | None,
        resumable_source_manager: ResumableSourceManager[ResumableData] | None,
    ) -> None:
        self._resource = source_response
        self._resource_name = source_response.name

        self._job = job
        self._reset_pipeline = reset_pipeline
        self._logger = logger
        self._load_id = time.time_ns()

        self._schema = schema
        self._source = source
        self._table = table
        self._is_incremental = schema.is_incremental or schema.is_webhook

        self._delta_table_helper = DeltaTableHelper(self._resource_name, self._job, self._logger)

        self._s3_batch_writer = S3BatchWriter(
            self._logger, self._job, str(self._schema.id), self._job.workflow_run_id, compression=PARQUET_COMPRESSION
        )

        sync_type: SyncTypeLiteral = "full_refresh"
        if self._schema.is_incremental or self._schema.is_webhook:
            sync_type = "incremental"
        elif self._schema.is_append:
            sync_type = "append"

        partition_count = self._schema.partition_count or self._resource.partition_count
        partition_size = self._schema.partition_size or self._resource.partition_size
        partition_keys = self._schema.partitioning_keys or self._resource.partition_keys or self._resource.primary_keys
        partition_format = self._schema.partition_format or self._resource.partition_format
        partition_mode = self._schema.partition_mode or self._resource.partition_mode

        # Determine if this is the first-ever sync (no DWH table exists yet)
        is_first_ever_sync = self._schema.table is None

        is_resume = resumable_source_manager is not None and resumable_source_manager.can_resume()

        self._kafka_producer = KafkaBatchProducer(
            team_id=self._job.team_id,
            job_id=str(self._job.id),
            schema_id=str(self._schema.id),
            source_id=str(self._schema.source_id),
            resource_name=self._resource_name,
            sync_type=sync_type,
            run_uuid=self._s3_batch_writer.get_run_uuid(),
            logger=self._logger,
            primary_keys=self._resource.primary_keys,
            is_resume=is_resume,
            partition_count=partition_count,
            partition_size=partition_size,
            partition_keys=partition_keys,
            partition_format=partition_format,
            partition_mode=partition_mode,
            is_first_ever_sync=is_first_ever_sync,
        )

        self._resumable_source_manager = resumable_source_manager
        self._batcher = Batcher(self._logger)
        self._internal_schema = HogQLSchema()
        self._cdp_producer = CDPProducer(
            team_id=self._job.team_id, schema_id=self._schema.id, job_id=job_id, logger=self._logger
        )
        self._accumulated_pa_schema = None
        self._shutdown_monitor = shutdown_monitor
        self._last_incremental_field_value: Any = None
        self._earliest_incremental_field_value: Any = process_incremental_value(
            schema.incremental_field_earliest_value, schema.incremental_field_type
        )
        self._batch_results = []

    async def run(self) -> PipelineResult:
        pa_memory_pool = pa.default_memory_pool()

        should_resume = self._resumable_source_manager is not None and self._resumable_source_manager.can_resume()
        source_is_resumable = self._resumable_source_manager is not None

        if should_resume:
            await self._logger.ainfo("V3 Pipeline: Resumable source detected - attempting to resume previous import")

        team_id_str = str(self._job.team_id)
        schema_id_str = str(self._schema.id)
        source_type = self._source.source_type if self._source else "unknown"
        sync_type = self._kafka_producer.sync_type

        start_time = time.perf_counter()
        status = "success"

        try:
            await cdp_producer_clear_chunks(self._cdp_producer)

            await reset_rows_synced_if_needed(self._job, self._is_incremental, self._reset_pipeline, should_resume)

            validate_incremental_sync(self._is_incremental, self._resource)

            await setup_row_tracking_with_billing_check(
                self._job.team_id,
                self._schema,
                self._resource,
                self._source,
                self._logger,
                billable=self._job.billable,
            )

            py_table = None
            row_count = 0
            chunk_index = 0

            await handle_reset_or_full_refresh(
                self._reset_pipeline, should_resume, self._schema, self._delta_table_helper, self._logger
            )

            is_fresh_sync = self._delta_table_helper.is_first_sync or self._schema.table is None
            if is_fresh_sync:
                self._kafka_producer.is_first_ever_sync = True

            async for item in async_iterate(self._resource.items()):
                py_table = None

                self._batcher.batch(item)
                if not self._batcher.should_yield():
                    continue

                py_table = self._batcher.get_table()
                row_count += py_table.num_rows

                await self._process_batch(
                    pa_table=py_table,
                    batch_index=chunk_index,
                    row_count=row_count,
                )

                if activity.in_activity():
                    get_rows_extracted_metric(team_id_str, schema_id_str, source_type).add(py_table.num_rows)
                    get_batches_produced_metric(team_id_str, schema_id_str).add(1)

                chunk_index += 1

                cleanup_memory(pa_memory_pool, py_table)
                py_table = None

                if should_check_shutdown(self._schema, self._resource, self._reset_pipeline, source_is_resumable):
                    self._shutdown_monitor.raise_if_is_worker_shutdown()

            if self._batcher.should_yield(include_incomplete_chunk=True):
                py_table = self._batcher.get_table()
                row_count += py_table.num_rows
                await self._process_batch(
                    pa_table=py_table,
                    batch_index=chunk_index,
                    row_count=row_count,
                )

                if activity.in_activity():
                    get_rows_extracted_metric(team_id_str, schema_id_str, source_type).add(py_table.num_rows)
                    get_batches_produced_metric(team_id_str, schema_id_str).add(1)

            await self._finalize(row_count=row_count)

            return {
                "should_trigger_cdp_producer": await self._cdp_producer.should_produce_table(),
                "consumer_manages_job_status": len(self._batch_results) > 0,
            }
        except Exception:
            status = "error"
            try:
                self._s3_batch_writer.cleanup()
            except Exception:
                self._logger.exception("V3 Pipeline: Failed to clean up S3 resources")
            raise
        finally:
            duration = time.perf_counter() - start_time
            if activity.in_activity():
                get_pipeline_run_duration_metric(team_id_str, source_type, sync_type, status).record(duration)

            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="warehouse_v3_extraction_completed",
                properties={
                    "team_id": self._job.team_id,
                    "schema_id": str(self._schema.id),
                    "source_type": source_type,
                    "sync_type": sync_type,
                    "status": status,
                    "duration_seconds": duration,
                    "total_batches": len(self._batch_results),
                    "total_rows": row_count if "row_count" in locals() else 0,
                },
            )

            self._logger.debug("V3 Pipeline: Cleaning up resources")
            del self._resource
            del self._s3_batch_writer
            del self._kafka_producer

            cleanup_memory(pa_memory_pool, py_table if "py_table" in locals() else None)

    async def _process_batch(self, pa_table: pa.Table, batch_index: int, row_count: int) -> None:
        pa_table = _append_debug_column_to_pyarrows_table(pa_table, self._load_id)
        pa_table = normalize_table_column_names(pa_table)

        pa_table = _evolve_pyarrow_schema(pa_table, None)
        pa_table = _handle_null_columns_with_definitions(pa_table, self._resource)

        # Add missing columns from previous batches for schema consistency
        if self._accumulated_pa_schema is not None:
            for field in self._accumulated_pa_schema:
                if field.name not in pa_table.schema.names:
                    null_column = pa.array([None] * pa_table.num_rows, type=field.type)
                    pa_table = pa_table.append_column(field, null_column)

        batch_result = await asyncio.to_thread(self._s3_batch_writer.write_batch, pa_table, batch_index)
        self._batch_results.append(batch_result)

        self._kafka_producer.send_batch_notification(batch_result, is_final_batch=False, cumulative_row_count=row_count)
        self._kafka_producer.flush()

        self._internal_schema.add_pyarrow_table(pa_table)

        await write_chunk_for_cdp_producer(self._cdp_producer, batch_index, pa_table)

        # Update accumulated schema with any new columns from this batch
        if self._accumulated_pa_schema is None:
            self._accumulated_pa_schema = pa_table.schema
        else:
            for field in pa_table.schema:
                if field.name not in self._accumulated_pa_schema.names:
                    self._accumulated_pa_schema = self._accumulated_pa_schema.append(field)

        (
            self._last_incremental_field_value,
            self._earliest_incremental_field_value,
        ) = await update_incremental_field_values(
            self._schema,
            pa_table,
            self._resource,
            self._last_incremental_field_value,
            self._earliest_incremental_field_value,
            self._logger,
            log_prefix="V3 Pipeline: ",
        )

        await update_row_tracking_after_batch(
            str(self._job.id), self._job.team_id, self._schema.id, pa_table.num_rows, self._logger
        )

    async def _finalize(self, row_count: int) -> None:
        total_batches = len(self._batch_results)

        if total_batches == 0:
            self._logger.debug("V3 Pipeline: No batches extracted, skipping finalization")
            return

        self._logger.info(
            f"V3 Pipeline: Finalizing extraction",
            total_batches=total_batches,
            total_rows=row_count,
        )

        schema_path = await asyncio.to_thread(self._s3_batch_writer.write_schema)

        final_batch = self._batch_results[-1]
        self._kafka_producer.send_batch_notification(
            final_batch,
            is_final_batch=True,
            total_batches=total_batches,
            total_rows=row_count,
            data_folder=self._s3_batch_writer.get_data_folder(),
            schema_path=schema_path,
            cumulative_row_count=row_count,
        )

        self._kafka_producer.flush()

        await finalize_desc_sort_incremental_value(
            self._resource, self._schema, self._last_incremental_field_value, self._logger, log_prefix="V3 Pipeline: "
        )

        if not self._schema.initial_sync_complete:
            await self._logger.adebug("V3 Pipeline: Setting initial_sync_complete on schema")
            await set_initial_sync_complete(schema_id=self._schema.id, team_id=self._job.team_id)

        await self._logger.ainfo(
            f"V3 Pipeline: Extraction complete",
            total_batches=total_batches,
            total_rows=row_count,
            base_folder=self._s3_batch_writer.get_base_folder(),
            schema_path=schema_path,
        )
