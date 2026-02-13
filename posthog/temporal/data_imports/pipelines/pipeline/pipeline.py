import sys
import time
import asyncio
import threading
from collections.abc import AsyncIterator, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Generic, Literal, TypeVar

import pyarrow as pa
import deltalake as deltalake
import posthoganalytics
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.shutdown import ShutdownMonitor
from posthog.temporal.data_imports.pipelines.common.extract import (
    cdp_producer_clear_chunks,
    write_chunk_for_cdp_producer,
)
from posthog.temporal.data_imports.pipelines.common.load import (
    get_incremental_field_value,
    supports_partial_data_loading,
    update_job_row_count,
)
from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.cdp_producer import CDPProducer
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from posthog.temporal.data_imports.pipelines.pipeline.typings import PipelineResult, ResumableData, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    BillingLimitsWillBeReachedException,
    DuplicatePrimaryKeysException,
    _append_debug_column_to_pyarrows_table,
    _evolve_pyarrow_schema,
    _handle_null_columns_with_definitions,
    normalize_table_column_names,
    setup_partitioning,
)
from posthog.temporal.data_imports.pipelines.pipeline_sync import (
    update_last_synced_at,
    validate_schema_and_update_table,
)
from posthog.temporal.data_imports.row_tracking import decrement_rows, increment_rows, will_hit_billing_limit
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.stripe.constants import CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying

from products.data_warehouse.backend.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.data_warehouse.backend.models.external_data_schema import process_incremental_value
from products.data_warehouse.backend.types import ExternalDataSourceType

T = TypeVar("T")

# Dedicated thread pool for source iteration so that long-running HTTP calls
# (e.g. Stripe API pagination) can't starve the default executor which is
# shared by logging, DB operations, and S3 writes.
_SOURCE_ITERATOR_EXECUTOR = ThreadPoolExecutor(max_workers=32, thread_name_prefix="source-iter")


async def async_iterate(iterable: Iterable[T]) -> AsyncIterator[T]:
    """
    Wrap a sync iterable to be used with `async for`.

    Each call to `next()` is run in a dedicated thread pool so that
    blocking source HTTP calls can't exhaust the default executor.
    """
    iterator = iter(iterable)
    lock = threading.Lock()
    loop = asyncio.get_running_loop()

    def _next() -> tuple[bool, T | None]:
        with lock:
            try:
                return (True, next(iterator))
            except StopIteration:
                return (False, None)

    def _close() -> None:
        with lock:
            if hasattr(iterator, "close") and callable(iterator.close):
                iterator.close()

    try:
        while True:
            has_value, item = await loop.run_in_executor(_SOURCE_ITERATOR_EXECUTOR, _next)
            if not has_value:
                break
            yield item  # type: ignore[misc]
    finally:
        await loop.run_in_executor(_SOURCE_ITERATOR_EXECUTOR, _close)


class PipelineNonDLT(Generic[ResumableData]):
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
    _internal_schema = HogQLSchema()
    _cdp_producer: CDPProducer
    _batcher: Batcher
    _load_id: int

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
        self._is_incremental = schema.is_incremental

        self._delta_table_helper = DeltaTableHelper(self._resource_name, self._job, self._logger)
        self._resumable_source_manager = resumable_source_manager
        self._batcher = Batcher(self._logger)
        self._internal_schema = HogQLSchema()
        self._cdp_producer = CDPProducer(
            team_id=self._job.team_id, schema_id=self._schema.id, job_id=job_id, logger=self._logger
        )
        self._shutdown_monitor = shutdown_monitor
        self._last_incremental_field_value: Any = None
        self._earliest_incremental_field_value: Any = process_incremental_value(
            schema.incremental_field_earliest_value, schema.incremental_field_type
        )

    async def run(self) -> PipelineResult:
        pa_memory_pool = pa.default_memory_pool()

        should_resume = self._resumable_source_manager is not None and self._resumable_source_manager.can_resume()
        source_is_resumable = self._resumable_source_manager is not None
        if should_resume:
            await self._logger.ainfo("Resumable source detected - attempting to resume previous import")

        try:
            await cdp_producer_clear_chunks(self._cdp_producer)
            # Reset the rows_synced count - this may not be 0 if the job restarted due to a heartbeat timeout
            if (
                self._job.rows_synced is not None
                and self._job.rows_synced != 0
                and (not self._is_incremental or self._reset_pipeline is True)
                and not should_resume
            ):
                self._job.rows_synced = 0
                await database_sync_to_async_pool(self._job.save)()

            # Check for duplicate primary keys
            if self._is_incremental and self._resource.has_duplicate_primary_keys:
                raise DuplicatePrimaryKeysException(
                    f"The primary keys for this table are not unique. We can't sync incrementally until the table has a unique primary key. Primary keys being used are: {self._resource.primary_keys}"
                )

            # Setup row tracking
            if self._resource.rows_to_sync:
                await increment_rows(self._job.team_id, self._schema.id, self._resource.rows_to_sync)

                # Check billing limits against incoming rows (skip for non-billable jobs)
                if self._job.billable and await will_hit_billing_limit(
                    team_id=self._job.team_id, source=self._source, logger=self._logger
                ):
                    raise BillingLimitsWillBeReachedException(
                        f"Your account will hit your Data Warehouse billing limits syncing {self._resource.name} with {self._resource.rows_to_sync} rows"
                    )

            py_table = None
            row_count = 0
            chunk_index = 0

            if self._reset_pipeline and not should_resume:
                await self._logger.adebug("Deleting existing table due to reset_pipeline being set")
                await self._delta_table_helper.reset_table()
                await database_sync_to_async_pool(self._schema.update_sync_type_config_for_reset_pipeline)()
            elif self._schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH and not should_resume:
                # Avoid schema mismatches from existing data about to be overwritten
                await self._logger.adebug("Deleting existing table due to sync being full refresh")
                await self._delta_table_helper.reset_table()
                await database_sync_to_async_pool(self._schema.update_sync_type_config_for_reset_pipeline)()

            # If the schema has no DWH table, it's a first ever sync
            is_first_ever_sync: bool = self._table is None

            async for item in async_iterate(self._resource.items()):
                py_table = None

                self._batcher.batch(item)
                if not self._batcher.should_yield():
                    continue

                py_table = self._batcher.get_table()

                row_count += py_table.num_rows

                await self._process_pa_table(
                    pa_table=py_table,
                    index=chunk_index,
                    resuming_sync=should_resume,
                    row_count=row_count,
                    is_first_ever_sync=is_first_ever_sync,
                )

                chunk_index += 1

                # Cleanup
                if "py_table" in locals() and py_table is not None:
                    del py_table
                pa_memory_pool.release_unused()

                # Only raise if we're not running in descending order, otherwise we'll often not
                # complete the job before the incremental value can be updated. Or if the source is
                # resumable
                # TODO: raise when we're within `x` time of the worker being forced to shutdown
                # Raising during a full reset will reset our progress back to 0 rows
                incremental_sync_raise_during_shutdown = (
                    self._schema.should_use_incremental_field
                    and self._resource.sort_mode != "desc"
                    and not self._reset_pipeline
                )
                if incremental_sync_raise_during_shutdown or source_is_resumable:
                    self._shutdown_monitor.raise_if_is_worker_shutdown()

            if self._batcher.should_yield(include_incomplete_chunk=True):
                py_table = self._batcher.get_table()
                row_count += py_table.num_rows
                await self._process_pa_table(
                    pa_table=py_table,
                    index=chunk_index,
                    resuming_sync=should_resume,
                    row_count=row_count,
                    is_first_ever_sync=is_first_ever_sync,
                )

            await self._post_run_operations(row_count=row_count)

            return {"should_trigger_cdp_producer": await self._cdp_producer.should_produce_table()}
        finally:
            # Help reduce the memory footprint of each job
            await self._logger.adebug("Cleaning up delta table helper")
            delta_table = await self._delta_table_helper.get_delta_table()
            self._delta_table_helper.get_delta_table.cache_clear()
            if delta_table:
                del delta_table

            del self._resource
            del self._delta_table_helper

            if "py_table" in locals() and py_table is not None:
                del py_table

            pa_memory_pool.release_unused()

    async def _process_pa_table(
        self, pa_table: pa.Table, index: int, resuming_sync: bool, row_count: int, is_first_ever_sync: bool
    ):
        delta_table = await self._delta_table_helper.get_delta_table()
        previous_file_uris = await self._delta_table_helper.get_file_uris()

        pa_table = _append_debug_column_to_pyarrows_table(pa_table, self._load_id)
        pa_table = normalize_table_column_names(pa_table)

        pa_table = await setup_partitioning(pa_table, delta_table, self._schema, self._resource, self._logger)

        pa_table = _evolve_pyarrow_schema(pa_table, delta_table.schema() if delta_table is not None else None)
        pa_table = _handle_null_columns_with_definitions(pa_table, self._resource)

        write_type: Literal["incremental", "full_refresh", "append"] = "full_refresh"
        if self._schema.is_incremental:
            write_type = "incremental"
        elif self._schema.is_append:
            write_type = "append"

        should_overwrite_table = index == 0 and not resuming_sync

        delta_table = await self._delta_table_helper.write_to_deltalake(
            pa_table,
            write_type,
            should_overwrite_table=should_overwrite_table,
            primary_keys=self._resource.primary_keys,
        )

        self._internal_schema.add_pyarrow_table(pa_table)

        await write_chunk_for_cdp_producer(self._cdp_producer, index, pa_table)

        # Update the incremental_field_last_value.
        # If the resource returns data sorted in ascending timestamp order, we can update the
        # `incremental_field_last_value` in the schema.
        # However, if the data is returned in descending order, we only want to update the
        # `incremental_field_last_value` once we have processed all of the data, otherwise if we fail halfway through,
        # we'd not process older data the next time we retry. But we do store the earliest available value so that we
        # can resume syncs if they stop mid way through without having to start from the beginning
        last_value = get_incremental_field_value(self._schema, pa_table)
        if last_value is not None:
            if (self._last_incremental_field_value is None) or (last_value > self._last_incremental_field_value):
                self._last_incremental_field_value = last_value

            if self._resource.sort_mode == "asc":
                await self._logger.adebug(
                    f"Updating incremental_field_last_value with {self._last_incremental_field_value}"
                )
                await database_sync_to_async_pool(self._schema.update_incremental_field_value)(
                    self._last_incremental_field_value
                )

            if self._resource.sort_mode == "desc":
                earliest_value = get_incremental_field_value(self._schema, pa_table, aggregate="min")

                if (
                    self._earliest_incremental_field_value is None
                    or earliest_value < self._earliest_incremental_field_value
                ):
                    self._earliest_incremental_field_value = earliest_value

                    await self._logger.adebug(f"Updating incremental_field_earliest_value with {earliest_value}")
                    await database_sync_to_async_pool(self._schema.update_incremental_field_value)(
                        earliest_value, type="earliest"
                    )

        await update_job_row_count(self._job.id, pa_table.num_rows, self._logger)
        await decrement_rows(self._job.team_id, self._schema.id, pa_table.num_rows)

        # if it's the first ever sync for this schema and the source supports partial data loading, we make the delta
        # table files available for querying and create the data warehouse table, so that the user has some data
        # available to start using
        # TODO - enable this for all source types
        if is_first_ever_sync and supports_partial_data_loading(self._schema):
            file_uris = await self._delta_table_helper.get_file_uris()

            await self._process_partial_data(
                previous_file_uris=previous_file_uris,
                file_uris=file_uris,
                row_count=row_count,
                chunk_index=index,
            )

    async def _process_partial_data(
        self, previous_file_uris: list[str], file_uris: list[str], row_count: int, chunk_index: int
    ):
        await self._logger.adebug(
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
                await self._logger.awarning(
                    "Should always be appending delta table files for a first time sync but found modified files!"
                )
                capture_exception(
                    Exception(
                        "Should always be appending delta table files for a first time sync but found modified files!"
                    )
                )
                return

        await self._logger.adebug(f"Adding {len(new_file_uris)} S3 files to query folder")
        folder_path = await database_sync_to_async_pool(self._job.folder_path)()
        queryable_folder = await prepare_s3_files_for_querying(
            folder_path=folder_path,
            table_name=self._resource_name,
            file_uris=new_file_uris,
            # delete existing files if it's the first chunk, otherwise we'll just append to the existing files
            delete_existing=chunk_index == 0,
            use_timestamped_folders=False,
            logger=self._logger,
        )
        await self._logger.adebug("Validating schema and updating table")
        await validate_schema_and_update_table(
            run_id=str(self._job.id),
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            table_schema_dict=self._internal_schema.to_hogql_types(),
            row_count=row_count,
            queryable_folder=queryable_folder,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )

    async def _post_run_operations(self, row_count: int):
        delta_table = await self._delta_table_helper.get_delta_table()

        if delta_table is None:
            await self._logger.adebug("No deltalake table, not continuing with post-run ops")
            return

        await self._logger.adebug("Triggering compaction and vacuuming on delta table")
        try:
            await self._delta_table_helper.compact_table()
        except Exception as e:
            capture_exception(e)
            await self._logger.aexception(f"Compaction failed: {e}", exc_info=e)

        file_uris = await self._delta_table_helper.get_file_uris()
        await self._logger.adebug(f"Preparing S3 files - total parquet files: {len(file_uris)}")

        folder_path = await database_sync_to_async_pool(self._job.folder_path)()
        existing_queryable_folder = self._table.queryable_folder if self._table else None
        queryable_folder = await prepare_s3_files_for_querying(
            folder_path,
            self._resource_name,
            file_uris,
            delete_existing=True,
            existing_queryable_folder=existing_queryable_folder,
            logger=self._logger,
        )

        await self._logger.adebug("Updating last synced at timestamp on schema")
        await update_last_synced_at(job_id=self._job.id, schema_id=self._schema.id, team_id=self._job.team_id)

        await self._logger.adebug("Notifying revenue analytics that sync has completed")
        await _notify_revenue_analytics_that_sync_has_completed(self._schema, self._source, self._logger)

        # As mentioned above, for sort mode 'desc' we only want to update the `incremental_field_last_value` once we
        # have processed all of the data (we could also update it here for 'asc' but it's not needed)
        if self._resource.sort_mode == "desc" and self._last_incremental_field_value is not None:
            await self._logger.adebug(
                f"Sort mode is 'desc' -> updating incremental_field_last_value with {self._last_incremental_field_value}"
            )
            await database_sync_to_async_pool(self._schema.refresh_from_db)()
            await database_sync_to_async_pool(self._schema.update_incremental_field_value)(
                self._last_incremental_field_value
            )

        await self._logger.adebug("Validating schema and updating table")
        await validate_schema_and_update_table(
            run_id=str(self._job.id),
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            table_schema_dict=self._internal_schema.to_hogql_types(),
            row_count=row_count,
            queryable_folder=queryable_folder,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )
        await self._logger.adebug("Finished validating schema and updating table")


async def _notify_revenue_analytics_that_sync_has_completed(
    schema: ExternalDataSchema, source: ExternalDataSource, logger: FilteringBoundLogger
) -> None:
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


def _estimate_size(obj: Any) -> int:
    if isinstance(obj, dict):
        return sys.getsizeof(obj) + sum(_estimate_size(k) + _estimate_size(v) for k, v in obj.items())
    elif isinstance(obj, list | tuple | set):
        return sys.getsizeof(obj) + sum(_estimate_size(i) for i in obj)
    else:
        return sys.getsizeof(obj)
