import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying

from products.data_warehouse.backend.data_load.create_table import create_table_from_saved_query
from products.data_warehouse.backend.models import DataWarehouseSavedQuery, DataWarehouseTable

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class PrepareQueryableTableInputs:
    team_id: int
    job_id: str
    saved_query_id: str
    table_uri: str
    file_uris: list[str]
    row_count: int


@database_sync_to_async
def _get_saved_query_with_table(inputs: PrepareQueryableTableInputs) -> DataWarehouseSavedQuery:
    saved_query = (
        DataWarehouseSavedQuery.objects.select_related("team", "table")
        .exclude(deleted=True)
        .get(id=inputs.saved_query_id, team_id=inputs.team_id)
    )
    return saved_query


@database_sync_to_async
def _update_saved_query_with_table(
    inputs: PrepareQueryableTableInputs, saved_query: DataWarehouseSavedQuery, saved_query_table: DataWarehouseTable
):
    saved_query.refresh_from_db()
    saved_query.table_id = saved_query_table.id
    saved_query.save()

    saved_query_table.row_count = inputs.row_count
    saved_query_table.save()


@activity.defn
async def prepare_queryable_table_activity(inputs: PrepareQueryableTableInputs):
    """Prepare materialized files for querying and create DataWarehouseTable."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    saved_query = await _get_saved_query_with_table(inputs)
    queryable_folder = saved_query.table.queryable_folder if saved_query.table else None
    await logger.adebug(
        f"Copying query files to S3: folder_path={saved_query.folder_path} table_name={saved_query.normalized_name} "
        f"existing_queryable_folder={queryable_folder}"
    )
    folder_path = prepare_s3_files_for_querying(
        folder_path=saved_query.folder_path,
        table_name=saved_query.normalized_name,
        file_uris=inputs.file_uris,
        preserve_table_name_casing=True,
        existing_queryable_folder=queryable_folder,
        logger=logger,
    )
    await logger.adebug("Creating DataWarehouseTable model")
    saved_query_table = await create_table_from_saved_query(
        inputs.job_id, inputs.saved_query_id, inputs.team_id, folder_path
    )

    await _update_saved_query_with_table(inputs, saved_query, saved_query_table)
    await logger.ainfo(f"Updated saved query row count: id={saved_query.id} row_count={inputs.row_count}")
