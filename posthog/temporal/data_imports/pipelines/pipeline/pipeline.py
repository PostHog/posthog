import gc
import time
from typing import Any

import deltalake as deltalake
import pyarrow as pa
from dlt.sources import DltSource

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.common.shutdown import ShutdownMonitor
from posthog.temporal.data_imports.deltalake_compaction_job import (
    trigger_compaction_job,
)
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    DeltaTableHelper,
)
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    _append_debug_column_to_pyarrows_table,
    _evolve_pyarrow_schema,
    _get_column_hints,
    _get_incremental_field_last_value,
    _get_primary_keys,
    _handle_null_columns_with_definitions,
    _notify_revenue_analytics_that_sync_has_completed,
    _update_job_row_count,
    append_partition_key_to_table,
    normalize_table_column_names,
    should_partition_table,
    supports_partial_data_loading,
    table_from_py_list,
)
from posthog.temporal.data_imports.pipelines.pipeline_sync import (
    update_last_synced_at_sync,
    validate_schema_and_update_table_sync,
)
from posthog.temporal.data_imports.row_tracking import decrement_rows, increment_rows
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying
from posthog.warehouse.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
)


class PipelineNonDLT:
    _resource: SourceResponse
    _resource_name: str
    _job: ExternalDataJob
    _schema: ExternalDataSchema
    _logger: FilteringBoundLogger
    _is_incremental: bool
    _reset_pipeline: bool
    _delta_table_helper: DeltaTableHelper
    _internal_schema = HogQLSchema()
    _load_id: int
    _chunk_size: int = 5000

    def __init__(
        self,
        source: DltSource | SourceResponse,
        logger: FilteringBoundLogger,
        job_id: str,
        is_incremental: bool,
        reset_pipeline: bool,
        shutdown_monitor: ShutdownMonitor,
    ) -> None:
        if isinstance(source, DltSource):
            resources = list(source.resources.items())
            assert len(resources) == 1
            resource_name, resource = resources[0]

            self._resource_name = resource_name
            self._resource = SourceResponse(
                items=resource,
                primary_keys=_get_primary_keys(resource),
                name=resource_name,
                column_hints=_get_column_hints(resource),
                partition_count=None,
            )
        else:
            self._resource = source
            self._resource_name = source.name

        self._job = ExternalDataJob.objects.prefetch_related("schema").get(id=job_id)
        self._is_incremental = is_incremental
        self._reset_pipeline = reset_pipeline
        self._logger = logger
        self._load_id = time.time_ns()

        schema: ExternalDataSchema | None = self._job.schema
        assert schema is not None
        self._schema = schema

        self._delta_table_helper = DeltaTableHelper(self._resource_name, self._job, self._logger)
        self._internal_schema = HogQLSchema()
        self._shutdown_monitor = shutdown_monitor
        self._last_incremental_field_value: Any = None

    def run(self):
        pa_memory_pool = pa.default_memory_pool()

        try:
            # Reset the rows_synced count - this may not be 0 if the job restarted due to a heartbeat timeout
            if (
                self._job.rows_synced is not None
                and self._job.rows_synced != 0
                and (not self._is_incremental or self._reset_pipeline is True)
            ):
                self._job.rows_synced = 0
                self._job.save()

            # Setup row tracking
            if self._resource.rows_to_sync:
                increment_rows(self._job.team_id, self._schema.id, self._resource.rows_to_sync)

            buffer: list[Any] = []
            py_table = None
            row_count = 0
            chunk_index = 0

            if self._reset_pipeline:
                self._logger.debug("Deleting existing table due to reset_pipeline being set")
                self._delta_table_helper.reset_table()
                self._schema.update_sync_type_config_for_reset_pipeline()
            elif self._schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH:
                # Avoid schema mismatches from existing data about to be overwritten
                self._logger.debug("Deleting existing table due to sync being full refresh")
                self._delta_table_helper.reset_table()
                self._schema.update_sync_type_config_for_reset_pipeline()

            # If the schema has no DWH table, it's a first ever sync
            is_first_ever_sync: bool = self._schema.table is None

            for item in self._resource.items:
                py_table = None

                if isinstance(item, list):
                    if len(buffer) > 0:
                        buffer.extend(item)
                        if len(buffer) >= self._chunk_size:
                            py_table = table_from_py_list(buffer)
                            buffer = []
                    else:
                        if len(item) >= self._chunk_size:
                            py_table = table_from_py_list(item)
                        else:
                            buffer.extend(item)
                            continue
                elif isinstance(item, dict):
                    buffer.append(item)
                    if len(buffer) < self._chunk_size:
                        continue

                    py_table = table_from_py_list(buffer)
                    buffer = []
                elif isinstance(item, pa.Table):
                    py_table = item
                else:
                    raise Exception(f"Unhandled item type: {item.__class__.__name__}")

                assert py_table is not None
                row_count += py_table.num_rows

                self._process_pa_table(
                    pa_table=py_table, index=chunk_index, row_count=row_count, is_first_ever_sync=is_first_ever_sync
                )

                chunk_index += 1

                # Cleanup
                if "py_table" in locals() and py_table is not None:
                    del py_table
                pa_memory_pool.release_unused()
                gc.collect()

                if self._is_incremental:
                    self._shutdown_monitor.raise_if_is_worker_shutdown()

            if len(buffer) > 0:
                py_table = table_from_py_list(buffer)
                row_count += py_table.num_rows
                self._process_pa_table(
                    pa_table=py_table, index=chunk_index, row_count=row_count, is_first_ever_sync=is_first_ever_sync
                )

            self._post_run_operations(row_count=row_count)
        finally:
            # Help reduce the memory footprint of each job
            delta_table = self._delta_table_helper.get_delta_table()
            self._delta_table_helper.get_delta_table.cache_clear()
            if delta_table:
                del delta_table

            del self._resource
            del self._delta_table_helper

            if "buffer" in locals() and buffer is not None:
                del buffer
            if "py_table" in locals() and py_table is not None:
                del py_table

            pa_memory_pool.release_unused()
            gc.collect()

    def _process_pa_table(self, pa_table: pa.Table, index: int, row_count: int, is_first_ever_sync: bool):
        delta_table = self._delta_table_helper.get_delta_table()
        previous_file_uris = delta_table.file_uris() if delta_table else []

        pa_table = _append_debug_column_to_pyarrows_table(pa_table, self._load_id)
        pa_table = normalize_table_column_names(pa_table)

        if should_partition_table(delta_table, self._schema, self._resource):
            partition_count = self._schema.partition_count or self._resource.partition_count
            partition_size = self._schema.partition_size or self._resource.partition_size
            partition_keys = self._schema.partitioning_keys or self._resource.primary_keys
            partition_format = self._schema.partition_format
            if partition_count and partition_keys and partition_size:
                # This needs to happen before _evolve_pyarrow_schema
                pa_table, partition_mode, updated_partition_keys = append_partition_key_to_table(
                    table=pa_table,
                    partition_count=partition_count,
                    partition_size=partition_size,
                    partition_keys=partition_keys,
                    partition_mode=self._schema.partition_mode,
                    partition_format=partition_format,
                    logger=self._logger,
                )

                if not self._schema.partitioning_enabled:
                    self._logger.debug(
                        f"Setting partitioning_enabled on schema with: partition_keys={partition_keys}. partition_count={partition_count}"
                    )
                    self._schema.set_partitioning_enabled(
                        updated_partition_keys, partition_count, partition_size, partition_mode
                    )
            else:
                self._logger.debug(
                    "Skipping partitioning due to missing partition_count or partition_keys or partition_size"
                )

        pa_table = _evolve_pyarrow_schema(pa_table, delta_table.schema() if delta_table is not None else None)
        pa_table = _handle_null_columns_with_definitions(pa_table, self._resource)

        delta_table = self._delta_table_helper.write_to_deltalake(
            pa_table, self._is_incremental, index, self._resource.primary_keys
        )

        self._internal_schema.add_pyarrow_table(pa_table)

        # Update the incremental_field_last_value.
        # If the resource returns data sorted in ascending timestamp order, we can update the
        # `incremental_field_last_value` in the schema.
        # However, if the data is returned in descending order, we only want to update the
        # `incremental_field_last_value` once we have processed all of the data, otherwise if we fail halfway through,
        # we'd not process older data the next time we retry.
        last_value = _get_incremental_field_last_value(self._schema, pa_table)
        if last_value is not None:
            if (self._last_incremental_field_value is None) or (last_value > self._last_incremental_field_value):
                self._last_incremental_field_value = last_value
            if self._resource.sort_mode == "asc":
                self._logger.debug(f"Updating incremental_field_last_value with {self._last_incremental_field_value}")
                self._schema.update_incremental_field_last_value(self._last_incremental_field_value)

        _update_job_row_count(self._job.id, pa_table.num_rows, self._logger)
        decrement_rows(self._job.team_id, self._schema.id, pa_table.num_rows)

        # if it's the first ever sync for this schema and the source supports partial data loading, we make the delta
        # table files available for querying and create the data warehouse table, so that the user has some data
        # available to start using
        # TODO - enable this for all source types
        if is_first_ever_sync and supports_partial_data_loading(self._schema):
            self._process_partial_data(
                previous_file_uris=previous_file_uris,
                file_uris=delta_table.file_uris(),
                row_count=row_count,
                chunk_index=index,
            )

    def _process_partial_data(
        self, previous_file_uris: list[str], file_uris: list[str], row_count: int, chunk_index: int
    ):
        self._logger.debug(
            "Source supports partial data loading and is first ever sync -> "
            "making delta table files available for querying and creating data warehouse table"
        )
        if chunk_index == 0:
            new_file_uris = file_uris
        else:
            new_file_uris = list(set(file_uris) - set(previous_file_uris))
            # in theory, we should always be appending files for a first time sync but we just check that this is the
            # case in case we update this assumption
            files_modified = set(previous_file_uris) - set(file_uris)
            if len(files_modified) > 0:
                self._logger.warning(
                    "Should always be appending delta table files for a first time sync but found modified files!"
                )
                capture_exception(
                    Exception(
                        "Should always be appending delta table files for a first time sync but found modified files!"
                    )
                )
                return

        self._logger.debug(f"Adding {len(new_file_uris)} S3 files to query folder")
        prepare_s3_files_for_querying(
            folder_path=self._job.folder_path(),
            table_name=self._resource_name,
            file_uris=new_file_uris,
            # delete existing files if it's the first chunk, otherwise we'll just append to the existing files
            delete_existing=chunk_index == 0,
        )
        self._logger.debug("Validating schema and updating table")
        validate_schema_and_update_table_sync(
            run_id=str(self._job.id),
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            table_schema_dict=self._internal_schema.to_hogql_types(),
            row_count=row_count,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )

    def _post_run_operations(self, row_count: int):
        delta_table = self._delta_table_helper.get_delta_table()

        if delta_table is None:
            self._logger.debug("No deltalake table, not continuing with post-run ops")
            return

        self._logger.debug("Triggering workflow to compact and vacuum")
        compaction_job_id = trigger_compaction_job(self._job, self._schema, self._logger)
        self._logger.debug(f"Compaction workflow id: {compaction_job_id}")

        file_uris = delta_table.file_uris()
        self._logger.debug(f"Preparing S3 files - total parquet files: {len(file_uris)}")
        prepare_s3_files_for_querying(self._job.folder_path(), self._resource_name, file_uris)

        self._logger.debug("Updating last synced at timestamp on schema")
        update_last_synced_at_sync(job_id=self._job.id, schema_id=self._schema.id, team_id=self._job.team_id)

        self._logger.debug("Notifying revenue analytics that sync has completed")
        _notify_revenue_analytics_that_sync_has_completed(self._schema, self._logger)

        # As mentioned above, for sort mode 'desc' we only want to update the `incremental_field_last_value` once we
        # have processed all of the data (we could also update it here for 'asc' but it's not needed)
        if self._resource.sort_mode == "desc" and self._last_incremental_field_value is not None:
            self._logger.debug(
                f"Sort mode is 'desc' -> updating incremental_field_last_value with {self._last_incremental_field_value}"
            )
            self._schema.refresh_from_db()
            self._schema.update_incremental_field_last_value(self._last_incremental_field_value)

        self._logger.debug("Validating schema and updating table")
        validate_schema_and_update_table_sync(
            run_id=str(self._job.id),
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            table_schema_dict=self._internal_schema.to_hogql_types(),
            row_count=row_count,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )
