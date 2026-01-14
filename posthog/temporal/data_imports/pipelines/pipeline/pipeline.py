import sys
import time
from typing import Any, Generic, Literal

import pyarrow as pa
import deltalake as deltalake
import posthoganalytics
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
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
from posthog.temporal.data_imports.pipelines.common.load import supports_partial_data_loading
from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline.typings import ResumableData, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    _append_debug_column_to_pyarrows_table,
    _evolve_pyarrow_schema,
    _handle_null_columns_with_definitions,
    normalize_table_column_names,
    setup_partitioning,
)
from posthog.temporal.data_imports.pipelines.pipeline_sync import (
    update_last_synced_at_sync,
    validate_schema_and_update_table_sync,
)
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.stripe.constants import CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying

from products.data_warehouse.backend.models import DataWarehouseTable, ExternalDataJob, ExternalDataSchema
from products.data_warehouse.backend.models.external_data_schema import process_incremental_value
from products.data_warehouse.backend.types import ExternalDataSourceType


class PipelineNonDLT(Generic[ResumableData]):
    _resource: SourceResponse
    _resource_name: str
    _job: ExternalDataJob
    _schema: ExternalDataSchema
    _logger: FilteringBoundLogger
    _is_incremental: bool
    _reset_pipeline: bool
    _delta_table_helper: DeltaTableHelper
    _resumable_source_manager: ResumableSourceManager[ResumableData] | None
    _internal_schema = HogQLSchema()
    _batcher: Batcher
    _load_id: int

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

        self._delta_table_helper = DeltaTableHelper(self._resource_name, self._job, self._logger)
        self._resumable_source_manager = resumable_source_manager
        self._batcher = Batcher(self._logger)
        self._internal_schema = HogQLSchema()
        self._shutdown_monitor = shutdown_monitor
        self._last_incremental_field_value: Any = None
        self._earliest_incremental_field_value: Any = process_incremental_value(
            schema.incremental_field_earliest_value, schema.incremental_field_type
        )

    def run(self):
        pa_memory_pool = pa.default_memory_pool()

        should_resume = self._resumable_source_manager is not None and self._resumable_source_manager.can_resume()
        source_is_resumable = self._resumable_source_manager is not None
        if should_resume:
            self._logger.info("Resumable source detected - attempting to resume previous import")

        py_table = None
        try:
            reset_rows_synced_if_needed(self._job, self._is_incremental, self._reset_pipeline, should_resume)

            validate_incremental_sync(self._is_incremental, self._resource)

            setup_row_tracking_with_billing_check(self._job.team_id, self._schema, self._resource, self._logger)

            row_count = 0
            chunk_index = 0

            handle_reset_or_full_refresh(
                self._reset_pipeline,
                should_resume,
                self._schema,
                self._delta_table_helper.reset_table,
                self._logger,
            )

            # If the schema has no DWH table, it's a first ever sync
            is_first_ever_sync: bool = self._schema.table is None

            for item in self._resource.items():
                py_table = None

                self._batcher.batch(item)
                if not self._batcher.should_yield():
                    continue

                py_table = self._batcher.get_table()

                row_count += py_table.num_rows

                self._process_pa_table(
                    pa_table=py_table,
                    index=chunk_index,
                    resuming_sync=should_resume,
                    row_count=row_count,
                    is_first_ever_sync=is_first_ever_sync,
                )

                chunk_index += 1

                cleanup_memory(pa_memory_pool, py_table)
                py_table = None

                if should_check_shutdown(self._schema, self._resource, self._reset_pipeline, source_is_resumable):
                    self._shutdown_monitor.raise_if_is_worker_shutdown()

            if self._batcher.should_yield(include_incomplete_chunk=True):
                py_table = self._batcher.get_table()
                row_count += py_table.num_rows
                self._process_pa_table(
                    pa_table=py_table,
                    index=chunk_index,
                    resuming_sync=should_resume,
                    row_count=row_count,
                    is_first_ever_sync=is_first_ever_sync,
                )

            self._post_run_operations(row_count=row_count)
        finally:
            # Help reduce the memory footprint of each job
            self._logger.debug("Cleaning up delta table helper")
            delta_table = self._delta_table_helper.get_delta_table()
            self._delta_table_helper.get_delta_table.cache_clear()
            if delta_table:
                del delta_table

            del self._resource
            del self._delta_table_helper

            cleanup_memory(pa_memory_pool, py_table)

    def _process_pa_table(
        self, pa_table: pa.Table, index: int, resuming_sync: bool, row_count: int, is_first_ever_sync: bool
    ):
        delta_table = self._delta_table_helper.get_delta_table()
        previous_file_uris = delta_table.file_uris() if delta_table else []

        pa_table = _append_debug_column_to_pyarrows_table(pa_table, self._load_id)
        pa_table = normalize_table_column_names(pa_table)

        pa_table = setup_partitioning(pa_table, delta_table, self._schema, self._resource, self._logger)

        pa_table = _evolve_pyarrow_schema(pa_table, delta_table.schema() if delta_table is not None else None)
        pa_table = _handle_null_columns_with_definitions(pa_table, self._resource)

        write_type: Literal["incremental", "full_refresh", "append"] = "full_refresh"
        if self._schema.is_incremental:
            write_type = "incremental"
        elif self._schema.is_append:
            write_type = "append"

        should_overwrite_table = index == 0 and not resuming_sync

        delta_table = self._delta_table_helper.write_to_deltalake(
            pa_table,
            write_type,
            should_overwrite_table=should_overwrite_table,
            primary_keys=self._resource.primary_keys,
        )

        self._internal_schema.add_pyarrow_table(pa_table)

        self._last_incremental_field_value, self._earliest_incremental_field_value = update_incremental_field_values(
            self._schema,
            pa_table,
            self._resource,
            self._last_incremental_field_value,
            self._earliest_incremental_field_value,
            self._logger,
        )

        update_row_tracking_after_batch(
            self._job.id, self._job.team_id, self._schema.id, pa_table.num_rows, self._logger
        )

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
        queryable_folder = prepare_s3_files_for_querying(
            folder_path=self._job.folder_path(),
            table_name=self._resource_name,
            file_uris=new_file_uris,
            # delete existing files if it's the first chunk, otherwise we'll just append to the existing files
            delete_existing=chunk_index == 0,
            use_timestamped_folders=False,
            logger=self._logger,
        )
        self._logger.debug("Validating schema and updating table")
        validate_schema_and_update_table_sync(
            run_id=str(self._job.id),
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            table_schema_dict=self._internal_schema.to_hogql_types(),
            row_count=row_count,
            queryable_folder=queryable_folder,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )

    def _post_run_operations(self, row_count: int):
        delta_table = self._delta_table_helper.get_delta_table()

        if delta_table is None:
            self._logger.debug("No deltalake table, not continuing with post-run ops")
            return

        self._logger.debug("Triggering compaction and vacuuming on delta table")
        try:
            self._delta_table_helper.compact_table()
        except Exception as e:
            capture_exception(e)
            self._logger.exception(f"Compaction failed: {e}", exc_info=e)

        file_uris = delta_table.file_uris()
        self._logger.debug(f"Preparing S3 files - total parquet files: {len(file_uris)}")
        queryable_folder = prepare_s3_files_for_querying(
            self._job.folder_path(),
            self._resource_name,
            file_uris,
            delete_existing=True,
            existing_queryable_folder=self._schema.table.queryable_folder if self._schema.table else None,
            logger=self._logger,
        )

        self._logger.debug("Updating last synced at timestamp on schema")
        update_last_synced_at_sync(job_id=self._job.id, schema_id=self._schema.id, team_id=self._job.team_id)

        self._logger.debug("Notifying revenue analytics that sync has completed")
        _notify_revenue_analytics_that_sync_has_completed(self._schema, self._logger)

        finalize_desc_sort_incremental_value(
            self._resource, self._schema, self._last_incremental_field_value, self._logger
        )

        self._logger.debug("Validating schema and updating table")
        validate_schema_and_update_table_sync(
            run_id=str(self._job.id),
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            table_schema_dict=self._internal_schema.to_hogql_types(),
            row_count=row_count,
            queryable_folder=queryable_folder,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )
        self._logger.debug("Finished validating schema and updating table")


def _notify_revenue_analytics_that_sync_has_completed(schema: ExternalDataSchema, logger: FilteringBoundLogger) -> None:
    try:
        if (
            schema.name == STRIPE_CHARGE_RESOURCE_NAME
            and schema.source.source_type == ExternalDataSourceType.STRIPE
            and schema.source.revenue_analytics_config.enabled
            and not schema.team.revenue_analytics_config.notified_first_sync
        ):
            # For every admin in the org, send a revenue analytics ready event
            # This will trigger a Campaign in PostHog and send an email
            for user in schema.team.all_users_with_access():
                if user.distinct_id is not None:
                    posthoganalytics.capture(
                        distinct_id=user.distinct_id,
                        event="revenue_analytics_ready",
                        properties={"source_type": schema.source.source_type},
                    )

            # Mark the team as notified, avoiding spamming emails
            schema.team.revenue_analytics_config.notified_first_sync = True
            schema.team.revenue_analytics_config.save()
    except Exception as e:
        # Silently fail, we don't want this to crash the pipeline
        # Sending an email is not critical to the pipeline
        logger.exception(f"Error notifying revenue analytics that sync has completed: {e}")
        capture_exception(e)


def _estimate_size(obj: Any) -> int:
    if isinstance(obj, dict):
        return sys.getsizeof(obj) + sum(_estimate_size(k) + _estimate_size(v) for k, v in obj.items())
    elif isinstance(obj, list | tuple | set):
        return sys.getsizeof(obj) + sum(_estimate_size(i) for i in obj)
    else:
        return sys.getsizeof(obj)
