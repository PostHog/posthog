import gc
import sys
import time
from typing import Any, Literal

from django.db.models import F

import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
import posthoganalytics
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.shutdown import ShutdownMonitor
from posthog.temporal.data_imports.deltalake_compaction_job import trigger_compaction_job
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    BillingLimitsWillBeReachedException,
    DuplicatePrimaryKeysException,
    _append_debug_column_to_pyarrows_table,
    _evolve_pyarrow_schema,
    _handle_null_columns_with_definitions,
    normalize_column_name,
    normalize_table_column_names,
    setup_partitioning,
    table_from_py_list,
)
from posthog.temporal.data_imports.pipelines.pipeline_sync import (
    update_last_synced_at_sync,
    validate_schema_and_update_table_sync,
)
from posthog.temporal.data_imports.row_tracking import decrement_rows, increment_rows, will_hit_billing_limit
from posthog.temporal.data_imports.sources.stripe.constants import CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying

from products.data_warehouse.backend.models import DataWarehouseTable, ExternalDataJob, ExternalDataSchema
from products.data_warehouse.backend.models.external_data_schema import process_incremental_value
from products.data_warehouse.backend.types import ExternalDataSourceType


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
    _chunk_size_bytes: int = 200 * 1024 * 1024  # 200 MiB

    def __init__(
        self,
        source: SourceResponse,
        logger: FilteringBoundLogger,
        job_id: str,
        reset_pipeline: bool,
        shutdown_monitor: ShutdownMonitor,
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
        self._internal_schema = HogQLSchema()
        self._shutdown_monitor = shutdown_monitor
        self._last_incremental_field_value: Any = None
        self._earliest_incremental_field_value: Any = process_incremental_value(
            schema.incremental_field_earliest_value, schema.incremental_field_type
        )

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

            # Check for duplicate primary keys
            if self._is_incremental and self._resource.has_duplicate_primary_keys:
                raise DuplicatePrimaryKeysException(
                    f"The primary keys for this table are not unique. We can't sync incrementally until the table has a unique primary key. Primary keys being used are: {self._resource.primary_keys}"
                )

            # Setup row tracking
            if self._resource.rows_to_sync:
                increment_rows(self._job.team_id, self._schema.id, self._resource.rows_to_sync)

                # Check billing limits against incoming rows
                if will_hit_billing_limit(team_id=self._job.team_id, logger=self._logger):
                    raise BillingLimitsWillBeReachedException(
                        f"Your account will hit your Data Warehouse billing limits syncing {self._resource.name} with {self._resource.rows_to_sync} rows"
                    )

            buffer: list[Any] = []
            buffer_size_bytes = 0
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
                        buffer_size_bytes += _estimate_size(item)
                        if buffer_size_bytes >= self._chunk_size_bytes or len(buffer) >= self._chunk_size:
                            self._logger.debug(f"Processing pipeline buffer (list). Length of buffer = {len(buffer)}")

                            py_table = table_from_py_list(buffer)
                            buffer = []
                            buffer_size_bytes = 0
                        else:
                            continue
                    else:
                        buffer_size_bytes += _estimate_size(item)
                        if buffer_size_bytes >= self._chunk_size_bytes or len(item) >= self._chunk_size:
                            self._logger.debug(f"Processing pipeline item (list). Length of item = {len(item)}")
                            py_table = table_from_py_list(item)
                            buffer_size_bytes = 0
                        else:
                            buffer.extend(item)
                            continue
                elif isinstance(item, dict):
                    buffer.append(item)
                    buffer_size_bytes += _estimate_size(item)
                    if buffer_size_bytes < self._chunk_size_bytes and len(buffer) < self._chunk_size:
                        continue

                    self._logger.debug(f"Processing pipeline buffer (dict). Length of buffer = {len(buffer)}")
                    py_table = table_from_py_list(buffer)
                    buffer = []
                    buffer_size_bytes = 0
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

                # Only raise if we're not running in descending order, otherwise we'll often not
                # complete the job before the incremental value can be updated
                # TODO: raise when we're within `x` time of the worker being forced to shutdown
                if (
                    self._schema.should_use_incremental_field
                    and self._resource.sort_mode != "desc"
                    and not self._reset_pipeline  # Raising during a full reset will reset our progress back to 0 rows
                ):
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
            self._logger.debug("Cleaning up delta table helper")
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

        pa_table = setup_partitioning(pa_table, delta_table, self._schema, self._resource, self._logger)

        pa_table = _evolve_pyarrow_schema(pa_table, delta_table.schema() if delta_table is not None else None)
        pa_table = _handle_null_columns_with_definitions(pa_table, self._resource)

        write_type: Literal["incremental", "full_refresh", "append"] = "full_refresh"
        if self._schema.is_incremental:
            write_type = "incremental"
        elif self._schema.is_append:
            write_type = "append"

        delta_table = self._delta_table_helper.write_to_deltalake(
            pa_table, write_type, index, self._resource.primary_keys
        )

        self._internal_schema.add_pyarrow_table(pa_table)

        # Update the incremental_field_last_value.
        # If the resource returns data sorted in ascending timestamp order, we can update the
        # `incremental_field_last_value` in the schema.
        # However, if the data is returned in descending order, we only want to update the
        # `incremental_field_last_value` once we have processed all of the data, otherwise if we fail halfway through,
        # we'd not process older data the next time we retry. But we do store the earliest available value so that we
        # can resume syncs if they stop mid way through without having to start from the beginning
        last_value = _get_incremental_field_value(self._schema, pa_table)
        if last_value is not None:
            if (self._last_incremental_field_value is None) or (last_value > self._last_incremental_field_value):
                self._last_incremental_field_value = last_value

            if self._resource.sort_mode == "asc":
                self._logger.debug(f"Updating incremental_field_last_value with {self._last_incremental_field_value}")
                self._schema.update_incremental_field_value(self._last_incremental_field_value)

            if self._resource.sort_mode == "desc":
                earliest_value = _get_incremental_field_value(self._schema, pa_table, aggregate="min")

                if (
                    self._earliest_incremental_field_value is None
                    or earliest_value < self._earliest_incremental_field_value
                ):
                    self._earliest_incremental_field_value = earliest_value

                    self._logger.debug(f"Updating incremental_field_earliest_value with {earliest_value}")
                    self._schema.update_incremental_field_value(earliest_value, type="earliest")

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

        self._logger.debug("Triggering workflow to compact and vacuum")
        compaction_job_id = trigger_compaction_job(self._job, self._schema, self._logger)
        self._logger.debug(f"Compaction workflow id: {compaction_job_id}")

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

        # As mentioned above, for sort mode 'desc' we only want to update the `incremental_field_last_value` once we
        # have processed all of the data (we could also update it here for 'asc' but it's not needed)
        if self._resource.sort_mode == "desc" and self._last_incremental_field_value is not None:
            self._logger.debug(
                f"Sort mode is 'desc' -> updating incremental_field_last_value with {self._last_incremental_field_value}"
            )
            self._schema.refresh_from_db()
            self._schema.update_incremental_field_value(self._last_incremental_field_value)

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


def _update_last_synced_at_sync(schema: ExternalDataSchema, job: ExternalDataJob) -> None:
    schema.last_synced_at = job.created_at
    schema.save()


def _update_job_row_count(job_id: str, count: int, logger: FilteringBoundLogger) -> None:
    logger.debug(f"Updating rows_synced with +{count}")
    ExternalDataJob.objects.filter(id=job_id).update(rows_synced=F("rows_synced") + count)


def _get_incremental_field_value(
    schema: ExternalDataSchema | None, table: pa.Table, aggregate: Literal["max"] | Literal["min"] = "max"
) -> Any:
    if schema is None or schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH:
        return

    incremental_field_name: str | None = schema.sync_type_config.get("incremental_field")
    if incremental_field_name is None:
        return

    column = table[normalize_column_name(incremental_field_name)]
    processed_column = pa.array(
        [process_incremental_value(val, schema.incremental_field_type) for val in column.to_pylist()]
    )

    if aggregate == "max":
        last_value = pc.max(processed_column)
    elif aggregate == "min":
        last_value = pc.min(processed_column)
    else:
        raise Exception(f"Unsupported aggregate function for _get_incremental_field_value: {aggregate}")

    return last_value.as_py()


def supports_partial_data_loading(schema: ExternalDataSchema) -> bool:
    """
    We should be able to roll this out to all source types but initially we only support it for Stripe so we can verify
    the approach.
    """
    return schema.source.source_type == ExternalDataSourceType.STRIPE


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
