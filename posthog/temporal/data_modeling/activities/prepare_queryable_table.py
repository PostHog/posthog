import asyncio
import dataclasses

import deltalake
from structlog import get_logger
from temporalio import activity

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.data_modeling.activities.materialize_view import get_aws_storage_options
from posthog.temporal.data_modeling.activities.utils import bind_data_modeling_log_context

from products.data_modeling.backend.facade.api import promote_view_nodes_to_matview
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.facade.api import create_table_from_saved_query
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.temporal import prepare_s3_files_for_querying

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class PrepareQueryableTableInputs:
    team_id: int
    job_id: str
    saved_query_id: str
    table_uri: str
    file_uris: list[str]
    row_count: int
    # An incremental run's row_count covers only the window it upserted, so it must not be written
    # to the table as a total. Defaulted so old workflow histories decode without it.
    incremental: bool = False


@database_sync_to_async_pool
def _get_saved_query_with_table(inputs: PrepareQueryableTableInputs) -> DataWarehouseSavedQuery:
    saved_query = (
        DataWarehouseSavedQuery.objects.select_related("team", "table")
        .exclude(deleted=True)
        .get(id=inputs.saved_query_id, team_id=inputs.team_id)
    )
    return saved_query


@database_sync_to_async_pool
def _update_saved_query_with_table(
    inputs: PrepareQueryableTableInputs, saved_query: DataWarehouseSavedQuery, saved_query_table: DataWarehouseTable
):
    saved_query.refresh_from_db()
    saved_query.table_id = saved_query_table.id
    saved_query.save()

    if not inputs.incremental:
        # `create_table_from_saved_query` already counted the published files, which is the whole
        # table. Keep that for an incremental run rather than overwriting it with the window.
        saved_query_table.row_count = inputs.row_count
        saved_query_table.save()

    # The table is what makes the query a matview, so this is the one place that always knows the
    # node type is stale — every other materialization entry point can leave it behind.
    promote_view_nodes_to_matview(saved_query)


async def _refresh_file_uris(table_uri: str) -> list[str]:
    storage_options = get_aws_storage_options()
    return await asyncio.to_thread(lambda: deltalake.DeltaTable(table_uri, storage_options=storage_options).file_uris())


@dataclasses.dataclass
class PrepareQueryableTableResult:
    storage_delta_mib: float | None
    total_storage_mib: float | None


@dataclasses.dataclass(frozen=False)
class StageQueryableFilesResult:
    staged_folder_path: str


@dataclasses.dataclass(frozen=False)
class PublishQueryableTableInputs(PrepareQueryableTableInputs):
    # Keyword-only so it can stay required behind the defaulted fields it inherits.
    staged_folder_path: str = dataclasses.field(kw_only=True)


async def _stage_files(inputs: PrepareQueryableTableInputs, saved_query: DataWarehouseSavedQuery, logger) -> str:
    queryable_folder = saved_query.table.queryable_folder if saved_query.table else None
    await logger.adebug(
        f"Copying query files to S3: folder_path={saved_query.folder_path} table_name={saved_query.normalized_name} "
        f"existing_queryable_folder={queryable_folder}"
    )
    return await prepare_s3_files_for_querying(
        folder_path=saved_query.folder_path,
        table_name=saved_query.normalized_name,
        file_uris=inputs.file_uris,
        preserve_table_name_casing=True,
        existing_queryable_folder=queryable_folder,
        logger=logger,
        refresh_file_uris=lambda: _refresh_file_uris(inputs.table_uri),
    )


async def _publish_table(
    inputs: PrepareQueryableTableInputs,
    saved_query: DataWarehouseSavedQuery,
    folder_path: str,
    logger,
) -> PrepareQueryableTableResult:
    await logger.ainfo("Preparing table for querying")
    create_result = await create_table_from_saved_query(
        inputs.job_id, inputs.saved_query_id, inputs.team_id, folder_path
    )

    await _update_saved_query_with_table(inputs, saved_query, create_result.table)
    await logger.ainfo(f"Updated saved query row count: id={saved_query.id} row_count={inputs.row_count}")

    return PrepareQueryableTableResult(
        storage_delta_mib=create_result.storage_delta_mib,
        total_storage_mib=create_result.total_storage_mib,
    )


@activity.defn
async def prepare_queryable_table_activity(inputs: PrepareQueryableTableInputs) -> PrepareQueryableTableResult:
    """Prepare materialized files for querying and create DataWarehouseTable.

    Returns storage metrics (delta and total MiB) for the materialized table.
    """
    bind_data_modeling_log_context(inputs.team_id, inputs.saved_query_id)
    logger = LOGGER.bind()

    saved_query = await _get_saved_query_with_table(inputs)
    folder_path = await _stage_files(inputs, saved_query, logger)
    return await _publish_table(inputs, saved_query, folder_path, logger)


@activity.defn
async def stage_queryable_files_activity(inputs: PrepareQueryableTableInputs) -> StageQueryableFilesResult:
    """Copy files into a new queryable folder, leaving the table pointed at the previous one."""
    bind_data_modeling_log_context(inputs.team_id, inputs.saved_query_id)
    logger = LOGGER.bind()

    saved_query = await _get_saved_query_with_table(inputs)
    folder_path = await _stage_files(inputs, saved_query, logger)
    return StageQueryableFilesResult(staged_folder_path=folder_path)


@activity.defn
async def publish_queryable_table_activity(inputs: PublishQueryableTableInputs) -> PrepareQueryableTableResult:
    """Repoint the table at a folder stage_queryable_files_activity already wrote."""
    bind_data_modeling_log_context(inputs.team_id, inputs.saved_query_id)
    logger = LOGGER.bind()

    saved_query = await _get_saved_query_with_table(inputs)
    return await _publish_table(inputs, saved_query, inputs.staged_folder_path, logger)
