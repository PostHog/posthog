import asyncio
import dataclasses

from django.db import transaction

import deltalake
from opentelemetry import trace
from structlog import get_logger
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool

from products.data_modeling.backend.facade.api import (
    link_table_if_materializing,
    promote_view_nodes_to_matview,
    unlink_table,
)
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_modeling.backend.temporal.activities.materialize_view import (
    LiveFiles,
    get_aws_storage_options,
    live_files,
)
from products.data_modeling.backend.temporal.activities.utils import bind_data_modeling_log_context
from products.data_warehouse.backend.facade.api import create_table_from_saved_query
from products.warehouse_sources.backend.facade.api import discard_backing_table
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.temporal import prepare_s3_files_for_querying

LOGGER = get_logger(__name__)
tracer = trace.get_tracer(__name__)


@frozen
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
    file_sizes: dict[str, int] = dataclasses.field(default_factory=dict)


BYTES_PER_MIB = 1024 * 1024


def staged_size_mib(table_uri: str, files: LiveFiles) -> float | None:
    relative_paths = [uri.removeprefix(f"{table_uri.rstrip('/')}/") for uri in files.uris]
    if any(path not in files.sizes_by_relative_path for path in relative_paths):
        return None
    return sum(files.sizes_by_relative_path[path] for path in relative_paths) / BYTES_PER_MIB


@database_sync_to_async_pool
def _get_saved_query_with_table(inputs: PrepareQueryableTableInputs) -> DataWarehouseSavedQuery:
    saved_query = (
        DataWarehouseSavedQuery.objects.select_related("team", "table")
        .exclude(deleted=True)
        .get(id=inputs.saved_query_id, team_id=inputs.team_id)
    )
    return saved_query


def _link_or_discard_table(saved_query: DataWarehouseSavedQuery, saved_query_table: DataWarehouseTable) -> bool:
    with transaction.atomic():
        if link_table_if_materializing(saved_query.team_id, saved_query.id, saved_query_table.id):
            return True
        unlink_table(saved_query.team_id, saved_query.id, saved_query_table.id)
        discard_backing_table(saved_query.team_id, saved_query_table.id)
    LOGGER.info(
        "discarded_table_published_after_revert",
        team_id=saved_query.team_id,
        saved_query_id=str(saved_query.id),
        table_id=str(saved_query_table.id),
    )
    return False


@database_sync_to_async_pool
def _update_saved_query_with_table(saved_query: DataWarehouseSavedQuery, saved_query_table: DataWarehouseTable):
    if not _link_or_discard_table(saved_query, saved_query_table):
        return

    # Every other materialization entry point can leave a stale node type behind, so repair it here.
    # A query reverted mid-run is left alone: it no longer asks to materialize.
    promote_view_nodes_to_matview(saved_query)


async def _read_live_files(table_uri: str) -> LiveFiles:
    storage_options = get_aws_storage_options()
    return await asyncio.to_thread(lambda: live_files(deltalake.DeltaTable(table_uri, storage_options=storage_options)))


@dataclasses.dataclass
class PrepareQueryableTableResult:
    storage_delta_mib: float | None
    total_storage_mib: float | None


@dataclasses.dataclass(frozen=False)
class StageQueryableFilesResult:
    staged_folder_path: str
    staged_size_mib: float | None = None


@frozen
class PublishQueryableTableInputs(PrepareQueryableTableInputs):
    # Keyword-only so it can stay required behind the defaulted fields it inherits.
    staged_folder_path: str = dataclasses.field(kw_only=True)
    staged_size_mib: float | None = None


@tracer.start_as_current_span("prepare_queryable_table.stage_files")
async def _stage_files(
    inputs: PrepareQueryableTableInputs, saved_query: DataWarehouseSavedQuery, logger
) -> StageQueryableFilesResult:
    trace.get_current_span().set_attribute("file_count", len(inputs.file_uris))
    queryable_folder = saved_query.table.queryable_folder if saved_query.table else None
    await logger.adebug(
        f"Copying query files to S3: folder_path={saved_query.folder_path} table_name={saved_query.storage_name} "
        f"existing_queryable_folder={queryable_folder}"
    )
    sizes = dict(inputs.file_sizes)
    live_uris = inputs.file_uris

    async def refresh_file_uris() -> list[str]:
        nonlocal live_uris
        refreshed = await _read_live_files(inputs.table_uri)
        sizes.clear()
        sizes.update(refreshed.sizes_by_relative_path)
        live_uris = refreshed.uris
        return live_uris

    staged_folder_path = await prepare_s3_files_for_querying(
        folder_path=saved_query.folder_path,
        table_name=saved_query.storage_name,
        file_uris=inputs.file_uris,
        preserve_table_name_casing=True,
        existing_queryable_folder=queryable_folder,
        logger=logger,
        refresh_file_uris=refresh_file_uris,
        file_sizes=sizes,
    )
    return StageQueryableFilesResult(
        staged_folder_path=staged_folder_path,
        staged_size_mib=staged_size_mib(inputs.table_uri, LiveFiles(uris=live_uris, sizes_by_relative_path=sizes)),
    )


async def _publish_table(
    inputs: PrepareQueryableTableInputs,
    saved_query: DataWarehouseSavedQuery,
    staged: StageQueryableFilesResult,
    logger,
) -> PrepareQueryableTableResult:
    await logger.ainfo("Preparing table for querying")
    folder_path = staged.staged_folder_path
    create_result = await create_table_from_saved_query(
        inputs.job_id,
        inputs.saved_query_id,
        inputs.team_id,
        folder_path,
        row_count=None if inputs.incremental else inputs.row_count,
        size_in_s3_mib=staged.staged_size_mib,
    )
    if not create_result.published:
        await logger.ainfo(
            "skipped_publish_of_older_staged_folder",
            saved_query_id=str(saved_query.id),
            table_id=str(create_result.table.id),
            staged_folder=folder_path,
        )

    with tracer.start_as_current_span("prepare_queryable_table.link_table"):
        await _update_saved_query_with_table(saved_query, create_result.table)
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
    staged = await _stage_files(inputs, saved_query, logger)
    return await _publish_table(inputs, saved_query, staged, logger)


@activity.defn
async def stage_queryable_files_activity(inputs: PrepareQueryableTableInputs) -> StageQueryableFilesResult:
    """Copy files into a new queryable folder, leaving the table pointed at the previous one."""
    bind_data_modeling_log_context(inputs.team_id, inputs.saved_query_id)
    logger = LOGGER.bind()

    saved_query = await _get_saved_query_with_table(inputs)
    return await _stage_files(inputs, saved_query, logger)


@activity.defn
async def publish_queryable_table_activity(inputs: PublishQueryableTableInputs) -> PrepareQueryableTableResult:
    """Repoint the table at a folder stage_queryable_files_activity already wrote."""
    bind_data_modeling_log_context(inputs.team_id, inputs.saved_query_id)
    logger = LOGGER.bind()

    saved_query = await _get_saved_query_with_table(inputs)
    staged = StageQueryableFilesResult(
        staged_folder_path=inputs.staged_folder_path, staged_size_mib=inputs.staged_size_mib
    )
    return await _publish_table(inputs, saved_query, staged, logger)
