import uuid
import dataclasses

from django.conf import settings
from django.db import IntegrityError

from asgiref.sync import sync_to_async
from clickhouse_driver.errors import ServerException
from structlog.contextvars import bind_contextvars

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.models.data_modeling_job import DataModelingJob
from products.data_modeling.backend.models.datawarehouse_saved_query import (
    DataWarehouseSavedQuery,
    aget_saved_query_by_id,
    aget_table_by_saved_query_id,
    asave_saved_query,
)
from products.data_warehouse.backend.s3 import get_size_of_folder
from products.warehouse_sources.backend.models.table import (
    DataWarehouseTable,
    acreate_datawarehousetable,
    asave_datawarehousetable,
)

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CreateTableResult:
    table: DataWarehouseTable
    storage_delta_mib: float | None
    total_storage_mib: float | None


async def calculate_table_size(saved_query: DataWarehouseSavedQuery, team_id: int, queryable_folder: str) -> float:
    bind_contextvars(team_id=team_id)
    logger = LOGGER.bind()

    await logger.adebug("Calculating table size in S3")

    folder_name = saved_query.folder_path
    s3_folder = f"{settings.BUCKET_URL}/{folder_name}/{queryable_folder}"

    total_mib = get_size_of_folder(s3_folder)

    await logger.adebug(f"Total size in MiB = {total_mib:.2f}")

    return total_mib


@database_sync_to_async
def aget_live_backing_table_by_name(team_id: int, name: str) -> DataWarehouseTable | None:
    # Self-managed (no external source) == a materialized view's backing table.
    return (
        DataWarehouseTable.objects.filter(team_id=team_id, name=name, external_data_source__isnull=True)
        .exclude(deleted=True)
        .order_by("-created_at")
        .first()
    )


@database_sync_to_async
def asoft_delete_table(table: DataWarehouseTable) -> None:
    table.soft_delete()


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

        table_params = {
            "name": table_name,
            "format": table_format,
            "url_pattern": url_pattern,
            "team_id": team_id,
            "queryable_folder": queryable_folder,
        }

        table_created: DataWarehouseTable | None = await aget_table_by_saved_query_id(saved_query_id_converted, team_id)
        if table_created is not None and table_created.deleted:
            table_created = None

        # No live linked table: retire any leftover backing row for this name, then create a fresh one.
        if table_created is None:
            leftover = await aget_live_backing_table_by_name(team_id, table_name)
            if leftover is not None:
                await asoft_delete_table(leftover)
            try:
                table_created = await acreate_datawarehousetable(**table_params)
            except IntegrityError:
                # Lost the create race to a concurrent run; reuse its row.
                table_created = await aget_live_backing_table_by_name(team_id, table_name)
                if table_created is None:
                    raise

        table_created.format = table_format
        table_created.url_pattern = url_pattern
        table_created.queryable_folder = queryable_folder
        await asave_datawarehousetable(table_created)

        assert isinstance(table_created, DataWarehouseTable) and table_created is not None

        # TODO: handle dlt columns schemas. Need to refactor dag pipeline to pass through schema or propagate from upstream tables
        table_created.columns = await sync_to_async(table_created.get_columns)()
        table_created.row_count = await database_sync_to_async(table_created.get_count)()
        await asave_datawarehousetable(table_created)

        refreshed_saved_query = await aget_saved_query_by_id(saved_query_id=saved_query_id_converted, team_id=team_id)

        storage_delta_mib: float | None = None
        total_storage_mib: float | None = None

        try:
            if refreshed_saved_query:
                existing_size: float = table_created.size_in_s3_mib or 0

                logger.debug(f"Existing size in MiB = {existing_size:.2f}")

                table_size = await calculate_table_size(refreshed_saved_query, team_id, queryable_folder)

                await logger.adebug(f"Total size in MiB = {table_size:.2f}")

                table_size_delta = table_size - existing_size
                logger.debug(f"Table size delta in MiB = {table_size_delta:.2f}")

                job.storage_delta_mib = (job.storage_delta_mib or 0) + table_size_delta
                await job.asave()

                table_created.size_in_s3_mib = table_size
                await asave_datawarehousetable(table_created)

                refreshed_saved_query.table = table_created
                await asave_saved_query(refreshed_saved_query)

                storage_delta_mib = job.storage_delta_mib
                total_storage_mib = table_created.size_in_s3_mib
        except Exception as e:
            capture_exception(e)
            await logger.adebug("Error raised from calcuting table size")
            await logger.adebug(str(e))

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
