import gc
import time
from typing import Any
import pyarrow as pa
from dlt.sources import DltSource, DltResource
import deltalake as deltalake
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    _handle_null_columns_with_definitions,
    _update_incremental_state,
    _get_primary_keys,
    _evolve_pyarrow_schema,
    _append_debug_column_to_pyarrows_table,
    _update_job_row_count,
    _update_last_synced_at_sync,
    table_from_py_list,
)
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline_sync import validate_schema_and_update_table_sync
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying
from posthog.warehouse.models import DataWarehouseTable, ExternalDataJob, ExternalDataSchema


class PipelineNonDLT:
    _resource: DltResource
    _resource_name: str
    _job: ExternalDataJob
    _schema: ExternalDataSchema
    _logger: FilteringBoundLogger
    _is_incremental: bool
    _reset_pipeline: bool
    _delta_table_helper: DeltaTableHelper
    _internal_schema = HogQLSchema()
    _load_id: int

    def __init__(
        self, source: DltSource, logger: FilteringBoundLogger, job_id: str, is_incremental: bool, reset_pipeline: bool
    ) -> None:
        resources = list(source.resources.items())
        assert len(resources) == 1
        resource_name, resource = resources[0]

        self._resource = resource
        self._resource_name = resource_name
        self._job = ExternalDataJob.objects.prefetch_related("schema").get(id=job_id)
        self._is_incremental = is_incremental
        self._reset_pipeline = reset_pipeline
        self._logger = logger
        self._load_id = time.time_ns()

        schema: ExternalDataSchema | None = self._job.schema
        assert schema is not None
        self._schema = schema

        self._delta_table_helper = DeltaTableHelper(resource_name, self._job, self._logger)
        self._internal_schema = HogQLSchema()

    def run(self):
        try:
            # Reset the rows_synced count - this may not be 0 if the job restarted due to a heartbeat timeout
            if self._job.rows_synced is not None and self._job.rows_synced != 0:
                self._job.rows_synced = 0
                self._job.save()

            buffer: list[Any] = []
            py_table = None
            chunk_size = 5000
            row_count = 0
            chunk_index = 0

            if self._reset_pipeline:
                self._logger.debug("Deleting existing table due to reset_pipeline being set")
                self._delta_table_helper.reset_table()

                self._schema.sync_type_config.pop("reset_pipeline", None)
                self._schema.sync_type_config.pop("incremental_field_last_value", None)
                self._schema.save()

            for item in self._resource:
                py_table = None

                if isinstance(item, list):
                    if len(buffer) > 0:
                        buffer.extend(item)
                        if len(buffer) >= chunk_size:
                            py_table = table_from_py_list(buffer)
                            buffer = []
                    else:
                        if len(item) >= chunk_size:
                            py_table = table_from_py_list(item)
                        else:
                            buffer.extend(item)
                            continue
                elif isinstance(item, dict):
                    buffer.append(item)
                    if len(buffer) < chunk_size:
                        continue

                    py_table = table_from_py_list(buffer)
                    buffer = []
                elif isinstance(item, pa.Table):
                    py_table = item
                else:
                    raise Exception(f"Unhandled item type: {item.__class__.__name__}")

                assert py_table is not None

                self._process_pa_table(pa_table=py_table, index=chunk_index)

                row_count += py_table.num_rows
                chunk_index += 1

            if len(buffer) > 0:
                py_table = table_from_py_list(buffer)
                self._process_pa_table(pa_table=py_table, index=chunk_index)
                row_count += py_table.num_rows

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
            gc.collect()

    def _process_pa_table(self, pa_table: pa.Table, index: int):
        delta_table = self._delta_table_helper.get_delta_table()

        pa_table = _append_debug_column_to_pyarrows_table(pa_table, self._load_id)
        pa_table = _evolve_pyarrow_schema(pa_table, delta_table.schema() if delta_table is not None else None)
        pa_table = _handle_null_columns_with_definitions(pa_table, self._resource)

        table_primary_keys = _get_primary_keys(self._resource)
        delta_table = self._delta_table_helper.write_to_deltalake(
            pa_table, self._is_incremental, index, table_primary_keys
        )

        self._internal_schema.add_pyarrow_table(pa_table)

        _update_incremental_state(self._schema, pa_table, self._logger)
        _update_job_row_count(self._job.id, pa_table.num_rows, self._logger)

    def _post_run_operations(self, row_count: int):
        delta_table = self._delta_table_helper.get_delta_table()

        if delta_table is None:
            self._logger.debug("No deltalake table, not continuing with post-run ops")
            return

        self._logger.debug("SKIPPING deltatable compact and vacuuming")

        # self._logger.debug("Spawning new process for deltatable compact and vacuuming")
        # try:
        #     process = subprocess.Popen(
        #         [
        #             "python",
        #             f"{os.getcwd()}/posthog/temporal/data_imports/pipelines/pipeline/delta_table_subprocess.py",
        #             "--table_uri",
        #             self._delta_table_helper._get_delta_table_uri(),
        #         ],
        #         stdout=subprocess.PIPE,
        #         stderr=subprocess.PIPE,
        #         close_fds=True,
        #     )
        #     stdout, stderr = process.communicate()

        #     if process.returncode != 0:
        #         raise Exception(f"Delta subprocess failed: {stderr.decode()}")
        # finally:
        #     if process.poll() is not None:
        #         process.kill()

        file_uris = delta_table.file_uris()
        self._logger.debug(f"Preparing S3 files - total parquet files: {len(file_uris)}")
        prepare_s3_files_for_querying(
            self._job.folder_path(), self._resource_name, file_uris, ExternalDataJob.PipelineVersion.V2
        )

        self._logger.debug("Updating last synced at timestamp on schema")
        _update_last_synced_at_sync(self._schema, self._job)

        self._logger.debug("Validating schema and updating table")

        validate_schema_and_update_table_sync(
            run_id=str(self._job.id),
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            table_schema={},
            table_schema_dict=self._internal_schema.to_hogql_types(),
            row_count=row_count,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )
