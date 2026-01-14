import time
from typing import Any, Generic

import pyarrow as pa
from structlog.types import FilteringBoundLogger

from posthog.temporal.common.shutdown import ShutdownMonitor
from posthog.temporal.data_imports.pipelines.common.extract import (
    cleanup_memory,
    finalize_desc_sort_incremental_value,
    handle_reset_or_full_refresh,
    reset_rows_synced_if_needed,
    setup_row_tracking_with_billing_check,
    should_check_shutdown,
    update_incremental_field_values,
    update_row_tracking_after_batch,
    validate_incremental_sync,
)
from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline.typings import ResumableData, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    _append_debug_column_to_pyarrows_table,
    _evolve_pyarrow_schema,
    _handle_null_columns_with_definitions,
    normalize_table_column_names,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka_batch_producer import KafkaBatchProducer
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3_batch_writer import BatchWriteResult, S3BatchWriter
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager

from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema
from products.data_warehouse.backend.models.external_data_schema import process_incremental_value

KAFKA_FLUSH_BATCH_SIZE = 100


class PipelineV3(Generic[ResumableData]):
    _resource: SourceResponse
    _resource_name: str
    _job: ExternalDataJob
    _schema: ExternalDataSchema
    _logger: FilteringBoundLogger
    _is_incremental: bool
    _reset_pipeline: bool
    _s3_batch_writer: S3BatchWriter
    _kafka_producer: KafkaBatchProducer
    _resumable_source_manager: ResumableSourceManager[ResumableData] | None
    _internal_schema: HogQLSchema
    _batcher: Batcher
    _load_id: int
    _batch_results: list[BatchWriteResult]

    def __init__(
        self,
        source: SourceResponse,
        logger: FilteringBoundLogger,
        job_id: str,
        reset_pipeline: bool,
        shutdown_monitor: ShutdownMonitor,
        resumable_source_manager: ResumableSourceManager[ResumableData] | None,
    ) -> None:
        self._resource = source
        self._resource_name = source.name

        self._job = ExternalDataJob.objects.prefetch_related("schema").get(id=job_id)
        self._reset_pipeline = reset_pipeline
        self._logger = logger
        self._load_id = time.time_ns()

        schema: ExternalDataSchema | None = self._job.schema
        assert schema is not None
        self._schema = schema
        self._is_incremental = schema.is_incremental

        self._s3_batch_writer = S3BatchWriter(self._job, self._logger, self._job.workflow_run_id)
        self._kafka_producer = KafkaBatchProducer(
            team_id=self._job.team_id,
            job_id=str(self._job.id),
            schema_id=str(self._schema.id),
            source_id=str(self._schema.source_id),
            resource_name=self._resource_name,
            sync_type=self._schema.sync_type or "full_refresh",
            run_uuid=self._s3_batch_writer.get_run_uuid(),
            logger=self._logger,
        )

        self._resumable_source_manager = resumable_source_manager
        self._batcher = Batcher(self._logger)
        self._internal_schema = HogQLSchema()
        self._shutdown_monitor = shutdown_monitor
        self._last_incremental_field_value: Any = None
        self._earliest_incremental_field_value: Any = process_incremental_value(
            schema.incremental_field_earliest_value, schema.incremental_field_type
        )
        self._batch_results = []

    def run(self) -> None:
        pa_memory_pool = pa.default_memory_pool()

        should_resume = self._resumable_source_manager is not None and self._resumable_source_manager.can_resume()
        source_is_resumable = self._resumable_source_manager is not None

        if should_resume:
            self._logger.info("V3 Pipeline: Resumable source detected - attempting to resume previous import")

        try:
            reset_rows_synced_if_needed(self._job, self._is_incremental, self._reset_pipeline, should_resume)

            validate_incremental_sync(self._is_incremental, self._resource)

            setup_row_tracking_with_billing_check(self._job.team_id, self._schema, self._resource, self._logger)

            py_table = None
            row_count = 0
            chunk_index = 0

            handle_reset_or_full_refresh(
                self._reset_pipeline,
                should_resume,
                self._schema,
                self._s3_batch_writer.cleanup,
                self._logger,
                log_prefix="V3 Pipeline: ",
            )

            for item in self._resource.items():
                py_table = None

                self._batcher.batch(item)
                if not self._batcher.should_yield():
                    continue

                py_table = self._batcher.get_table()
                row_count += py_table.num_rows

                self._process_batch(
                    pa_table=py_table,
                    batch_index=chunk_index,
                    row_count=row_count,
                )

                chunk_index += 1

                cleanup_memory(pa_memory_pool, py_table)
                py_table = None

                if should_check_shutdown(self._schema, self._resource, self._reset_pipeline, source_is_resumable):
                    self._shutdown_monitor.raise_if_is_worker_shutdown()

                if len(self._batch_results) >= KAFKA_FLUSH_BATCH_SIZE:
                    self._kafka_producer.flush()  # TODO: handle errors while flushing

            if self._batcher.should_yield(include_incomplete_chunk=True):
                py_table = self._batcher.get_table()
                row_count += py_table.num_rows
                self._process_batch(
                    pa_table=py_table,
                    batch_index=chunk_index,
                    row_count=row_count,
                )

            self._finalize(row_count=row_count)

        finally:
            self._logger.debug("V3 Pipeline: Cleaning up resources")
            del self._resource
            del self._s3_batch_writer

            cleanup_memory(pa_memory_pool, py_table if "py_table" in locals() else None)

    def _process_batch(self, pa_table: pa.Table, batch_index: int, row_count: int) -> None:
        pa_table = _append_debug_column_to_pyarrows_table(
            pa_table, self._load_id
        )  # TODO: probably change this to another type of debug column
        pa_table = normalize_table_column_names(pa_table)

        existing_schema = self._internal_schema.to_pyarrow_schema() if batch_index > 0 else None
        pa_table = _evolve_pyarrow_schema(pa_table, existing_schema)
        pa_table = _handle_null_columns_with_definitions(pa_table, self._resource)

        batch_result = self._s3_batch_writer.write_batch(pa_table, batch_index)
        self._batch_results.append(batch_result)

        self._kafka_producer.send_batch_notification(batch_result, is_final_batch=False)

        self._internal_schema.add_pyarrow_table(pa_table)

        self._last_incremental_field_value, self._earliest_incremental_field_value = update_incremental_field_values(
            self._schema,
            pa_table,
            self._resource,
            self._last_incremental_field_value,
            self._earliest_incremental_field_value,
            self._logger,
            log_prefix="V3 Pipeline: ",
        )

        update_row_tracking_after_batch(
            self._job.id, self._job.team_id, self._schema.id, pa_table.num_rows, self._logger
        )

    def _finalize(self, row_count: int) -> None:
        total_batches = len(self._batch_results)

        if total_batches == 0:
            self._logger.debug("V3 Pipeline: No batches extracted, skipping finalization")
            return

        self._logger.info(
            f"V3 Pipeline: Finalizing extraction",
            total_batches=total_batches,
            total_rows=row_count,
        )

        schema_path = self._s3_batch_writer.write_schema()

        final_batch = self._batch_results[-1]
        self._kafka_producer.send_batch_notification(
            final_batch,
            is_final_batch=True,
            total_batches=total_batches,
            total_rows=row_count,
            data_folder=self._s3_batch_writer.get_data_folder(),
            schema_path=schema_path,
        )

        self._kafka_producer.flush()  # TODO: handle errors while flushing

        finalize_desc_sort_incremental_value(
            self._resource, self._schema, self._last_incremental_field_value, self._logger, log_prefix="V3 Pipeline: "
        )

        self._logger.info(
            f"V3 Pipeline: Extraction complete",
            total_batches=total_batches,
            total_rows=row_count,
            base_folder=self._s3_batch_writer.get_base_folder(),
            schema_path=schema_path,
        )
