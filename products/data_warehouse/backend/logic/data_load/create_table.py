import uuid
import asyncio
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from django.conf import settings
from django.db import transaction

from clickhouse_driver.errors import ServerException
from opentelemetry import trace
from structlog.contextvars import bind_contextvars

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async, database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade import api as modeling_api
from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataWarehouseSavedQuery,
    aget_saved_query_by_id,
)
from products.data_warehouse.backend.s3 import get_size_of_folder
from products.warehouse_sources.backend.facade.api import publish_backing_table
from products.warehouse_sources.backend.facade.contracts import BackingTableSnapshot
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.types import DataWarehouseTableCreatedVia, DataWarehouseTableFormat

LOGGER = get_logger(__name__)
tracer = trace.get_tracer(__name__)

_R = TypeVar("_R")

MAX_CONCURRENT_DESCRIBE_AND_COUNT = 2
_describe_and_count_executor = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_DESCRIBE_AND_COUNT, thread_name_prefix="describe-and-count"
)


def _in_span(name: str, call: Callable[[], _R]) -> Callable[[], _R]:
    @functools.wraps(call)
    def call_in_span() -> _R:
        with tracer.start_as_current_span(name):
            return call()

    return call_in_span


@frozen
class CreateTableResult:
    table: DataWarehouseTable
    published: bool
    storage_delta_mib: float | None
    total_storage_mib: float | None


async def _record_storage_delta(
    job: DataModelingJob, size_in_s3_mib: float | None, replaced_size_in_s3_mib: float | None
) -> float | None:
    if size_in_s3_mib is None:
        return None
    job.storage_delta_mib = (job.storage_delta_mib or 0) + size_in_s3_mib - (replaced_size_in_s3_mib or 0)
    await job.asave(update_fields=["storage_delta_mib", "updated_at"])
    return job.storage_delta_mib


@database_sync_to_async_pool
def _get_or_create_table_for_saved_query(
    saved_query_id: str,
    team_id: int,
    name: str,
    table_format: str,
    url_pattern: str,
    queryable_folder: str,
) -> DataWarehouseTable:
    with transaction.atomic():
        saved_query = (
            DataWarehouseSavedQuery.objects.select_for_update()
            .exclude(deleted=True)
            .get(id=saved_query_id, team_id=team_id)
        )
        if saved_query.table_id is not None:
            return DataWarehouseTable.objects.get(id=saved_query.table_id, team_id=team_id)

        table = DataWarehouseTable.objects.create(
            name=name,
            format=table_format,
            url_pattern=url_pattern,
            team_id=team_id,
            queryable_folder=queryable_folder,
            created_via=DataWarehouseTableCreatedVia.MATERIALIZED_VIEW,
        )
        saved_query.table = table
        saved_query.save(update_fields=["table", "updated_at"])
        return table


@tracer.start_as_current_span("create_table_from_saved_query.folder_size")
async def calculate_table_size(saved_query: DataWarehouseSavedQuery, team_id: int, queryable_folder: str) -> float:
    bind_contextvars(team_id=team_id)
    logger = LOGGER.bind()

    await logger.adebug("Calculating table size in S3")

    folder_name = saved_query.folder_path
    s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{queryable_folder}"

    total_mib = await asyncio.to_thread(get_size_of_folder, s3_folder)

    await logger.adebug(f"Total size in MiB = {total_mib:.2f}")

    return total_mib


async def create_table_from_saved_query(
    job_id: str,
    saved_query_id: str,
    team_id: int,
    queryable_folder: str,
    row_count: int | None = None,
    size_in_s3_mib: float | None = None,
) -> CreateTableResult:
    """
    Create a table from a saved query if it doesn't exist.
    """
    bind_contextvars(team_id=team_id)
    logger = LOGGER.bind()

    saved_query_id_converted = str(uuid.UUID(saved_query_id))
    saved_query = await aget_saved_query_by_id(saved_query_id=saved_query_id_converted, team_id=team_id)
    if saved_query is None:
        raise ValueError(f"Saved query {saved_query_id_converted} not found")

    # nosemgrep: idor-lookup-without-team (internal Temporal activity, not API-exposed)
    job = await DataModelingJob.objects.aget(id=job_id)

    try:
        table_name = f"{saved_query.name}"
        url_pattern = saved_query.url_pattern
        table_format = DataWarehouseTableFormat.DeltaS3Wrapper

        table_created = await _get_or_create_table_for_saved_query(
            saved_query_id=saved_query_id_converted,
            team_id=team_id,
            name=table_name,
            table_format=table_format,
            url_pattern=url_pattern,
            queryable_folder=queryable_folder,
        )
        table_created.format = table_format
        table_created.url_pattern = url_pattern
        table_created.queryable_folder = queryable_folder

        # TODO: handle dlt columns schemas. Need to refactor dag pipeline to pass through schema or propagate from upstream tables
        # set_columns records the DESCRIBE column order (which follows the view's SELECT order for
        # materialized backing tables) alongside `columns`, since jsonb loses key order.
        with tracer.start_as_current_span("create_table_from_saved_query.describe_columns"):
            columns = await database_sync_to_async_pool(
                _in_span("create_table_from_saved_query.describe_columns.run", table_created.get_columns),
                executor=_describe_and_count_executor,
            )()
        table_created.set_columns(columns)
        if row_count is None:
            with tracer.start_as_current_span("create_table_from_saved_query.count_rows"):
                row_count = await database_sync_to_async_pool(
                    _in_span("create_table_from_saved_query.count_rows.run", table_created.get_count),
                    executor=_describe_and_count_executor,
                )()
        table_created.row_count = row_count

        table_created.size_in_s3_mib = size_in_s3_mib
        if size_in_s3_mib is None:
            refreshed_saved_query = await aget_saved_query_by_id(
                saved_query_id=saved_query_id_converted, team_id=team_id
            )
            try:
                if refreshed_saved_query:
                    table_created.size_in_s3_mib = await calculate_table_size(
                        refreshed_saved_query, team_id, queryable_folder
                    )
            except Exception as e:
                capture_exception(e)
                await logger.adebug("Error raised from calcuting table size")
                await logger.adebug(str(e))

        publish = await database_sync_to_async_pool(publish_backing_table)(
            team_id,
            table_created.id,
            BackingTableSnapshot(
                format=table_format,
                url_pattern=url_pattern,
                queryable_folder=queryable_folder,
                columns=columns,
                row_count=table_created.row_count,
                size_in_s3_mib=table_created.size_in_s3_mib,
            ),
        )
        if publish is None:
            return CreateTableResult(
                table=table_created, published=False, storage_delta_mib=None, total_storage_mib=None
            )

        if publish.columns_changed:
            await database_sync_to_async(modeling_api.schedule_downstream_view_column_refresh)(
                team_id, saved_query.id, None
            )

        return CreateTableResult(
            table=table_created,
            published=True,
            storage_delta_mib=await _record_storage_delta(
                job, table_created.size_in_s3_mib, publish.replaced_size_in_s3_mib
            ),
            total_storage_mib=table_created.size_in_s3_mib,
        )
    except ServerException as err:
        logger.exception(
            f"Data Warehouse: Unknown ServerException {saved_query.pk}",
            exc_info=err,
        )
        raise
    except Exception as e:
        # TODO: handle other exceptions here
        logger.exception(
            f"Data Warehouse: Could not validate schema for saved query materialization{saved_query.pk}",
            exc_info=e,
        )
        raise
