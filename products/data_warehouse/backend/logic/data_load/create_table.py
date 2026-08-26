import uuid
import dataclasses

from django.conf import settings
from django.db import transaction

from asgiref.sync import sync_to_async
from clickhouse_driver.errors import ServerException
from structlog.contextvars import bind_contextvars

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async, database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataWarehouseSavedQuery,
    aget_saved_query_by_id,
)
from products.data_warehouse.backend.s3 import get_size_of_folder
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, asave_datawarehousetable

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CreateTableResult:
    table: DataWarehouseTable
    storage_delta_mib: float | None
    total_storage_mib: float | None


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
            created_via=DataWarehouseTable.CreatedVia.MATERIALIZED_VIEW,
        )
        saved_query.table = table
        saved_query.save(update_fields=["table", "updated_at"])
        return table


async def calculate_table_size(saved_query: DataWarehouseSavedQuery, team_id: int, queryable_folder: str) -> float:
    bind_contextvars(team_id=team_id)
    logger = LOGGER.bind()

    await logger.adebug("Calculating table size in S3")

    folder_name = saved_query.folder_path
    s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{queryable_folder}"

    total_mib = get_size_of_folder(s3_folder)

    await logger.adebug(f"Total size in MiB = {total_mib:.2f}")

    return total_mib


async def create_table_from_saved_query(
    job_id: str,
    saved_query_id: str,
    team_id: int,
    queryable_folder: str,
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
        table_format = DataWarehouseTable.TableFormat.DeltaS3Wrapper

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
        table_created.set_columns(await sync_to_async(table_created.get_columns)())
        table_created.row_count = await database_sync_to_async(table_created.get_count)()

        refreshed_saved_query = await aget_saved_query_by_id(saved_query_id=saved_query_id_converted, team_id=team_id)

        storage_delta_mib: float | None = None
        total_storage_mib: float | None = None
        existing_size: float = table_created.size_in_s3_mib or 0
        table_created.size_in_s3_mib = None

        try:
            if refreshed_saved_query:
                logger.debug(f"Existing size in MiB = {existing_size:.2f}")

                table_size = await calculate_table_size(refreshed_saved_query, team_id, queryable_folder)

                await logger.adebug(f"Total size in MiB = {table_size:.2f}")

                table_created.size_in_s3_mib = table_size
                table_size_delta = table_size - existing_size
                logger.debug(f"Table size delta in MiB = {table_size_delta:.2f}")

                job.storage_delta_mib = (job.storage_delta_mib or 0) + table_size_delta
                await job.asave(update_fields=["storage_delta_mib", "updated_at"])

                storage_delta_mib = job.storage_delta_mib
                total_storage_mib = table_created.size_in_s3_mib
        except Exception as e:
            capture_exception(e)
            await logger.adebug("Error raised from calcuting table size")
            await logger.adebug(str(e))

        await asave_datawarehousetable(table_created)

        return CreateTableResult(
            table=table_created,
            storage_delta_mib=storage_delta_mib,
            total_storage_mib=total_storage_mib,
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
