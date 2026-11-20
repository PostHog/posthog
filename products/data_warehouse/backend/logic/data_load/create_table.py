import uuid
import asyncio
import functools
import dataclasses
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
from products.warehouse_sources.backend.facade.api import query_folder_staged_at
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.types import DataWarehouseTableCreatedVia, DataWarehouseTableFormat

LOGGER = get_logger(__name__)
tracer = trace.get_tracer(__name__)

_R = TypeVar("_R")

MAX_CONCURRENT_DESCRIBE_AND_COUNT = 2
_describe_and_count_executor = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_DESCRIBE_AND_COUNT, thread_name_prefix="describe-and-count"
)

PUBLISHED_TABLE_FIELDS = [
    "format",
    "url_pattern",
    "queryable_folder",
    "created_via",
    "columns",
    "column_order",
    "row_count",
    "size_in_s3_mib",
    "updated_at",
]


def _in_span(name: str, call: Callable[[], _R]) -> Callable[[], _R]:
    @functools.wraps(call)
    def call_in_span() -> _R:
        with tracer.start_as_current_span(name):
            return call()

    return call_in_span


@dataclasses.dataclass
class CreateTableResult:
    table: DataWarehouseTable
    storage_delta_mib: float | None
    total_storage_mib: float | None


@frozen
class _PublishedTable:
    table: DataWarehouseTable
    storage_delta_mib: float | None
    columns_changed: bool


def _a_newer_folder_is_published(published_folder: str | None, staged_folder: str | None) -> bool:
    published_at = query_folder_staged_at(published_folder)
    staged_at = query_folder_staged_at(staged_folder)
    return published_at is not None and staged_at is not None and published_at > staged_at


@database_sync_to_async_pool
def _publish_staged_table(staged_table: DataWarehouseTable, job: DataModelingJob) -> _PublishedTable:
    with transaction.atomic():
        published_table = DataWarehouseTable.raw_objects.select_for_update().get(
            id=staged_table.id, team_id=staged_table.team_id
        )
        if _a_newer_folder_is_published(published_table.queryable_folder, staged_table.queryable_folder):
            return _PublishedTable(table=published_table, storage_delta_mib=None, columns_changed=False)

        storage_delta_mib: float | None = None
        if staged_table.size_in_s3_mib is not None:
            job.storage_delta_mib = (
                (job.storage_delta_mib or 0) + staged_table.size_in_s3_mib - (published_table.size_in_s3_mib or 0)
            )
            job.save(update_fields=["storage_delta_mib", "updated_at"])
            storage_delta_mib = job.storage_delta_mib

        staged_table.save(update_fields=PUBLISHED_TABLE_FIELDS, internally_computed_url_pattern=True)
        return _PublishedTable(
            table=staged_table,
            storage_delta_mib=storage_delta_mib,
            columns_changed=(published_table.columns, published_table.column_order)
            != (staged_table.columns, staged_table.column_order),
        )


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
        # Backing tables created before created_via existed have no value. Without the marker, the
        # save below rejects a backing table for a model in the models namespace.
        if table_created.created_via is None:
            table_created.created_via = DataWarehouseTableCreatedVia.MATERIALIZED_VIEW

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

        refreshed_saved_query = await aget_saved_query_by_id(saved_query_id=saved_query_id_converted, team_id=team_id)

        table_created.size_in_s3_mib = None

        try:
            if refreshed_saved_query:
                table_created.size_in_s3_mib = await calculate_table_size(
                    refreshed_saved_query, team_id, queryable_folder
                )
        except Exception as e:
            capture_exception(e)
            await logger.adebug("Error raised from calcuting table size")
            await logger.adebug(str(e))

        published = await _publish_staged_table(table_created, job)
        if published.columns_changed:
            await database_sync_to_async(modeling_api.schedule_downstream_view_column_refresh)(
                team_id, saved_query.id, None
            )

        return CreateTableResult(
            table=published.table,
            storage_delta_mib=published.storage_delta_mib,
            total_storage_mib=published.table.size_in_s3_mib,
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
