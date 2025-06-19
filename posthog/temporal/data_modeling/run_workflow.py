import asyncio
import collections
import collections.abc
import dataclasses
import datetime as dt
import enum
import json
import os
import re
import typing
import uuid

import asyncstdlib
import deltalake
import temporalio.activity
import temporalio.common
import temporalio.exceptions
import temporalio.workflow
from temporalio import workflow
from deltalake import DeltaTable
from django.conf import settings

from posthog.exceptions_capture import capture_exception
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.models import Team
from posthog.settings.base_variables import TEST
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import FilteringBoundLogger, bind_temporal_worker_logger
from posthog.temporal.common.shutdown import ShutdownMonitor
from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying
from posthog.warehouse.data_load.create_table import create_table_from_saved_query
from posthog.warehouse.models import (
    DataWarehouseModelPath,
    DataWarehouseSavedQuery,
    DataWarehouseTable,
    get_s3_client,
)
from posthog.warehouse.models.data_modeling_job import DataModelingJob
from posthog.warehouse.util import database_sync_to_async
from posthog.warehouse.api.lineage import get_upstream_dag

# preserve casing since we are already coming from a sql dialect, we don't need to worry about normalizing
os.environ["SCHEMA__NAMING"] = "direct"


class EmptyHogQLResponseColumnsError(Exception):
    def __init__(self):
        super().__init__("After running a HogQL query, no columns where returned")


class DataModelingCancelledException(Exception):
    """Exception raised when a data modeling job is cancelled."""

    pass


@dataclasses.dataclass(frozen=True)
class ModelNode:
    """A node representing a model in a DAG.

    Attributes:
        label: The model's label, which represents the model in all paths.
        children: A set of labels from all this model's direct children. This implies the
            existence of an edge from this model to each of the children.
        parents: A set of labels from all this model's direct parents. This implies the
            existence of an edge from each of the parents to this model.
    """

    label: str
    children: set[str] = dataclasses.field(default_factory=set)
    parents: set[str] = dataclasses.field(default_factory=set)
    selected: bool = False

    def as_selected(self, selected: bool) -> "ModelNode":
        return ModelNode(label=self.label, children=self.children, parents=self.parents, selected=selected)


DAG = dict[str, ModelNode]


@dataclasses.dataclass
class RunDagActivityInputs:
    """Inputs for `run_dag_activity`.

    Attributes:
        team_id: The team ID of the team whom this DAG belongs in.
        dag: The DAG to run.
            We require the DAG to be represented as a dictionary of model labels to
            `ModelNode` instances, as this is useful for the algorithm that
            `run_dag_activity` executes. See it for more details.
    """

    team_id: int
    dag: DAG
    job_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
        }


class ModelStatus(enum.StrEnum):
    """The status a model in the queue can be in."""

    COMPLETED = "Completed"
    FAILED = "Failed"
    READY = "Ready"


@dataclasses.dataclass
class QueueMessage:
    """A queue message used to orchestrate the running of a DAG."""

    status: ModelStatus
    label: str
    error: str | None = None


Results = collections.namedtuple("Results", ("completed", "failed", "ancestor_failed"))

NullablePattern = re.compile(r"Nullable\((.*)\)")


class CHQueryErrorMemoryLimitExceeded(Exception):
    """Exception raised when a ClickHouse query exceeds memory limits."""

    pass


class CannotCoerceColumnException(Exception):
    """Exception raised when column types cannot be coerced."""

    pass


async def handle_model_ready(model: ModelNode, team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    shutdown_monitor: ShutdownMonitor,
) -> None:
    """Handle a model that is ready to run by materializing.

    After materializing is done, we can report back to the execution queue the result. If
    the model is not marked as `selected`, then it doesn't need to be materialized, and we
    can immediately put it back in the queue as `ModelStatus.COMPLETED`.

    Args:
        model: The model we are trying to run.
        team_id: The ID of the team who owns this model.
        job_id: The ID of the job that is running this model.
    """

    job = await database_sync_to_async(DataModelingJob.objects.get)(id=job_id)
    try:
        if model.selected is True:
            team = await database_sync_to_async(Team.objects.get)(id=team_id)
            saved_query = await get_saved_query(team, model.label)

            saved_query.progress = f"Updating current view..."
            await database_sync_to_async(saved_query.save)()
            await materialize_model(model.label, team, saved_query, job, logger, shutdown_monitor, False)
    except CHQueryErrorMemoryLimitExceeded as err:
        await logger.aexception("Memory limit exceeded for model %s", model.label, job_id=job_id)
        await handle_error(job, model, queue, err, "Memory limit exceeded for model %s: %s", logger)
    except CannotCoerceColumnException as err:
        await logger.aexception("Type coercion error for model %s", model.label, job_id=job_id)
        await handle_error(job, model, queue, err, "Type coercion error for model %s: %s", logger)
    except DataModelingCancelledException as err:
        await logger.aexception("Data modeling run was cancelled for model %s", model.label, job_id=job_id)
        await handle_cancelled(job, model, queue, err, "Data modeling run was cancelled for model %s: %s", logger)
    except Exception as err:
        await logger.aexception(
            "Failed to materialize model %s due to unexpected error: %s", model.label, str(err), job_id=job_id
        )
        capture_exception(err)
        await handle_error(job, model, queue, err, "Failed to materialize model %s due to error: %s", logger)
    else:
        await logger.ainfo("Materialized model %s", model.label)

    finally:
        pass


async def handle_error(
    job: DataModelingJob,
    model: ModelNode,
    queue: asyncio.Queue[QueueMessage],
    error: Exception,
    error_message: str,
    logger: FilteringBoundLogger,
):
    if job:
        await logger.ainfo("Marking job %s as failed", job.id)
        await logger.aerror(f"handle_error: error={error}. error_message={error_message}")
        job.status = DataModelingJob.Status.FAILED
        job.error = str(error)
        await database_sync_to_async(job.save)()


async def handle_cancelled(
    job: DataModelingJob,
    model: ModelNode,
    queue: asyncio.Queue[QueueMessage],
    error: Exception,
    error_message: str,
    logger: FilteringBoundLogger,
):
    if job:
        await logger.aerror(f"handle_cancelled: error={error}. error_message={error_message}")
        job.status = DataModelingJob.Status.CANCELLED
        job.error = str(error)
        await database_sync_to_async(job.save)()


async def start_job_modeling_run(
    team: Team, workflow_id: str, workflow_run_id: str, saved_query: DataWarehouseSavedQuery | None
) -> DataModelingJob:
    """Create a DataModelingJob record in an async-safe way."""
    job_create = database_sync_to_async(DataModelingJob.objects.create)
    return await job_create(
        team=team,
        saved_query=saved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        created_by_id=saved_query.created_by_id if saved_query is not None else None,
    )


async def get_saved_query(team: Team, model_label: str) -> DataWarehouseSavedQuery:
    filter_params: dict[str, str | uuid.UUID] = {}
    try:
        model_id = uuid.UUID(model_label)
        filter_params["id"] = model_id
    except ValueError:
        model_name = model_label
        filter_params["name"] = model_name

    return await database_sync_to_async(
        DataWarehouseSavedQuery.objects.prefetch_related("team")
        .exclude(deleted=True)
        .filter(team=team, **filter_params)
        .get
    )()


async def materialize_model(
    model_label: str,
    team: Team,
    saved_query: DataWarehouseSavedQuery,
    job: DataModelingJob,
    logger: FilteringBoundLogger,
    shutdown_monitor: ShutdownMonitor,
) -> tuple[str, DeltaTable, uuid.UUID]:
    """Materialize a given model by running its query and piping the results into a delta table.

    Arguments:
        model_label: A label representing the ID or the name of the model to materialize.
            If it's a valid UUID, then we will assume it's the ID, otherwise we'll assume
            it is the model's name.
        team: The team the model belongs to.
        saved_query: The saved query to materialize.
        job: The DataModelingJob record for this run that tracks the lifecycle and rows of the run.
    """
    await logger.adebug(f"Starting materialize_model for {model_label}. saved_query.name={saved_query.name}")

    query_columns = saved_query.columns
    if not query_columns:
        query_columns = await database_sync_to_async(saved_query.get_columns)()

    hogql_query = saved_query.query["query"]

    try:
        row_count = 0

        table_uri = f"{settings.BUCKET_URL}/team_{team.pk}_model_{model_label}/modeling/{saved_query.normalized_name}"
        storage_options = _get_credentials()

        await logger.adebug(f"Delta table URI = {table_uri}")

        # Delete existing table first so that there are no schema conflicts
        s3 = get_s3_client()
        try:
            await logger.adebug(f"Deleting existing delta table at {table_uri}")
            s3.delete(table_uri, recursive=True)
            await logger.adebug("Table deleted")
        except FileNotFoundError:
            await logger.adebug(f"Table at {table_uri} not found - skipping deletion")

        async for index, batch in asyncstdlib.enumerate(hogql_table(hogql_query, team, logger)):
            mode: typing.Literal["error", "append", "overwrite", "ignore"] = "append"
            schema_mode: typing.Literal["merge", "overwrite"] | None = "merge"
            if index == 0:
                mode = "overwrite"
                schema_mode = "overwrite"

            await logger.adebug(
                f"Writing batch to delta table. index={index}. mode={mode}. batch_row_count={batch.num_rows}"
            )

            deltalake.write_deltalake(
                table_or_uri=table_uri, storage_options=storage_options, data=batch, mode=mode, schema_mode=schema_mode
            )

            row_count = row_count + batch.num_rows

            shutdown_monitor.raise_if_is_worker_shutdown()

        await logger.adebug(f"Finished writing to delta table. row_count={row_count}")
        delta_table = deltalake.DeltaTable(table_uri=table_uri, storage_options=storage_options)
    except Exception as e:
        error_message = str(e)
        if "Query exceeds memory limits" in error_message:
            saved_query.latest_error = error_message
            await database_sync_to_async(saved_query.save)()
            await mark_job_as_failed(job, error_message, logger)
            raise CHQueryErrorMemoryLimitExceeded(
                f"Query for model {model_label} exceeds memory limits. Try reducing its scope by changing the time range."
            ) from e

        elif "Cannot coerce type" in error_message:
            saved_query.latest_error = error_message
            await database_sync_to_async(saved_query.save)()
            await mark_job_as_failed(job, error_message, logger)

            raise CannotCoerceColumnException(f"Type coercion error in model {model_label}: {error_message}") from e
        else:
            saved_query.latest_error = f"Failed to materialize model {model_label}"
            error_message = "Your query failed to materialize. If this query ran for a long time, try optimizing it."
            await logger.aerror("Failed to materialize model with unexpected error: %s", str(e))
            await database_sync_to_async(saved_query.save)()
            await mark_job_as_failed(job, error_message, logger)
            raise Exception(f"Failed to materialize model {model_label}: {error_message}") from e

    data_modeling_job = await database_sync_to_async(DataModelingJob.objects.get)(id=job.id)
    if data_modeling_job.status == DataModelingJob.Status.CANCELLED:
        raise DataModelingCancelledException("Data modeling run was cancelled")

    await logger.adebug("Compacting delta table")
    delta_table.optimize.compact()
    await logger.adebug("Vacuuming delta table")
    delta_table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)

    file_uris = delta_table.file_uris()

    await logger.adebug("Copying query files in S3")
    prepare_s3_files_for_querying(saved_query.folder_path, saved_query.normalized_name, file_uris, True)

    await update_table_row_count(saved_query, row_count, logger)

    # Update the job record with the row count and completed status if we are updating the current model
    if not is_upstream:
        job.rows_materialized = row_count
        job.status = DataModelingJob.Status.COMPLETED
        job.last_run_at = dt.datetime.now(dt.UTC)
        await database_sync_to_async(job.save)()

    await logger.adebug("Setting DataModelingJob.Status = COMPLETED")

    return (saved_query.normalized_name, delta_table, job.id)


async def mark_job_as_failed(job: DataModelingJob, error_message: str, logger: FilteringBoundLogger) -> None:
    """
    Mark DataModelingJob as failed
    """

    await logger.aerror(f"mark_job_as_failed: {error_message}")
    await logger.ainfo("Marking job %s as failed", job.id)
    job.status = DataModelingJob.Status.FAILED
    job.error = error_message
    await database_sync_to_async(job.save)()


async def update_table_row_count(
    saved_query: DataWarehouseSavedQuery, row_count: int, logger: FilteringBoundLogger
) -> None:
    try:
        table = None
        if saved_query.table_id:
            table = await database_sync_to_async(DataWarehouseTable.objects.get)(id=saved_query.table_id)

        if table:
            table.row_count = row_count
            await database_sync_to_async(table.save)()
            await logger.ainfo("Updated row count for table %s to %d", saved_query.name, row_count)
        else:
            capture_exception(
                ValueError(f"Could not find DataWarehouseTable record for saved query {saved_query.name}")
            )
            await logger.aexception("Could not find DataWarehouseTable record for saved query %s", saved_query.name)
    except Exception as e:
        capture_exception(e)
        await logger.aexception("Failed to update row count for table %s: %s", saved_query.name, str(e))


async def hogql_table(query: str, team: Team, logger: FilteringBoundLogger):
    """A HogQL table given by a HogQL query."""

    query_node = parse_select(query)

    context = HogQLContext(
        team=team,
        team_id=team.id,
        enable_select_queries=True,
        limit_top_select=False,
    )
    context.output_format = "TabSeparatedWithNamesAndTypes"
    context.database = await database_sync_to_async(create_hogql_database)(team=team, modifiers=context.modifiers)

    prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
        query_node, context=context, dialect="clickhouse", stack=[]
    )
    printed = await database_sync_to_async(print_prepared_ast)(
        prepared_hogql_query,
        context=context,
        dialect="clickhouse",
        stack=[],
    )

    await logger.adebug(f"Running clickhouse query: {printed}")

    async with get_client() as client:
        async for batch, pa_schema in client.astream_query_in_batches(printed, query_parameters=context.values):
            yield table_from_py_list(batch, pa_schema)


def _get_credentials():
    if TEST:
        return {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    return {
        "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
        "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
        "region_name": settings.AIRBYTE_BUCKET_REGION,
        "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


@dataclasses.dataclass(frozen=True)
class Selector:
    """A selector represents the models to select from a set of paths.

    Attributes:
        label: The model we are selecting around.
        ancestors: How many ancestors to select from the model from each of the paths.
        descendants: How many descendants to select from the model from each of the paths.
    """

    label: str
    ancestors: int | typing.Literal["ALL"] = 0
    descendants: int | typing.Literal["ALL"] = 0


Paths = list[str]
SelectorPaths = dict[Selector, Paths]


@dataclasses.dataclass
class BuildDagActivityInputs:
    team_id: int
    select: list[Selector] = dataclasses.field(default_factory=list)

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
        }


class InvalidSelector(Exception):
    def __init__(self, invalid_input: str):
        super().__init__(f"invalid selector: '{invalid_input}'")


@temporalio.activity.defn
async def build_dag_activity(inputs: BuildDagActivityInputs) -> DAG:
    """Construct a DAG from provided selector inputs."""

    logger = await bind_temporal_worker_logger(inputs.team_id)
    await logger.adebug(f"starting build_dag_activity. selectors = {[select.label for select in inputs.select]}")

    async with Heartbeater():
        selector_paths: SelectorPaths = {}

        if not inputs.select:
            matching_paths = await database_sync_to_async(list)(
                DataWarehouseModelPath.objects.filter(team_id=inputs.team_id).values_list("path", flat=True)
            )
            selector_paths[
                Selector(
                    label="*",
                    ancestors="ALL",
                    descendants="ALL",
                )
            ] = matching_paths
            await logger.adebug(f"No selectors passed. Selecting all model paths")

        for selector_input in inputs.select:
            query = f"*.{selector_input.label}.*"

            # TODO: Make this one database fetch for all selectors, instead of one per selector
            matching_paths = await database_sync_to_async(list)(
                DataWarehouseModelPath.objects.filter(team_id=inputs.team_id, path__lquery=query).values_list(
                    "path", flat=True
                )
            )

            selector_paths[selector_input] = matching_paths

        dag = await build_dag_from_selectors(selector_paths=selector_paths, team_id=inputs.team_id)

        return dag


async def build_dag_from_selectors(selector_paths: SelectorPaths, team_id: int) -> DAG:
    """Build a DAG from a list of `DataWarehouseModelPath` paths.

    Our particular representation of a DAG includes all edges directly with each of the
    nodes, as each `ModelNode` instance contains the label of each of its children and
    parents, which implies the existence of edges between them.

    This particular representation of a DAG is useful for `run_dag_activity`, which needs
    to locate nodes by label (thus, our DAG is a dictionary) and then check their children
    and parents (thus both of these are sets already included with the node). Naturally,
    this means that the same children and parents appear in multiple nodes.

    The cost of the redundancy of this representation is larger memory use, but we assume
    that simple strings and sets won't blow things up until we grow massively. If that
    ever does happen, some solution involving another level of indirection by storing
    indexes to a list of nodes could be implemented. Good luck!
    """
    posthog_tables = await get_posthog_tables(team_id)
    dag = {}

    for selector, paths in selector_paths.items():
        ancestors_offset = selector.ancestors
        descendants_offset = selector.descendants

        for path in paths:
            if selector.label == "*":
                label_index = -1
                start = 0
                end = len(path)

            else:
                label_index = path.index(selector.label)

                if ancestors_offset == "ALL":
                    start = 0
                else:
                    start = max(label_index - ancestors_offset, 0)

                if descendants_offset == "ALL":
                    end = len(path)
                else:
                    end = min(label_index + descendants_offset, len(path) - 1)

            for index, label in enumerate(path):
                if label not in dag:
                    dag[label] = ModelNode(label=label)

                node = dag[label]

                if (
                    (index == label_index or end >= index >= start)
                    and label not in posthog_tables
                    and node.selected is False
                ):
                    node = dag[label] = node.as_selected(True)

                if index > 0:
                    parent_node = path[index - 1]
                    node.parents.add(parent_node)

                if index < len(path) - 1:
                    child_node = path[index + 1]
                    node.children.add(child_node)

    return dag


async def get_posthog_tables(team_id: int) -> list[str]:
    team = await database_sync_to_async(Team.objects.get)(id=team_id)
    hogql_db = await database_sync_to_async(create_hogql_database)(team=team)
    posthog_tables = hogql_db.get_posthog_tables()
    return posthog_tables


@dataclasses.dataclass
class StartRunActivityInputs:
    models_to_run: list[str]
    root_model_id: str
    run_at: str
    team_id: int

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "run_at": self.run_at,
        }


@dataclasses.dataclass
class CreateJobsForMaterializedViewsActivityInputs:
    team_id: int
    materialized_view_ids: list[str]


@temporalio.activity.defn
async def create_jobs_for_materialized_views_activity(
    inputs: CreateJobsForMaterializedViewsActivityInputs,
) -> dict[str, str]:
    team = await database_sync_to_async(Team.objects.get)(id=inputs.team_id)
    workflow_id = temporalio.activity.info().workflow_id
    workflow_run_id = temporalio.activity.info().workflow_run_id

    jobs = {}
    for model_id in inputs.materialized_view_ids:
        saved_query = await get_saved_query(team, model_id)
        job = await start_job_modeling_run(
            team=team,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            saved_query=saved_query,
        )
        jobs[model_id] = str(job.id)
    return jobs


@dataclasses.dataclass
class CreateJobModelInputs:
    team_id: int
    select: list[Selector]


@temporalio.activity.defn
async def create_job_model_activity(inputs: CreateJobModelInputs) -> str:
    logger = await bind_temporal_worker_logger(inputs.team_id)

    await logger.adebug(f"Creating DataModelingJob for {[selector.label for selector in inputs.select]}")

    team = await database_sync_to_async(Team.objects.get)(id=inputs.team_id)
    workflow_id = temporalio.activity.info().workflow_id
    workflow_run_id = temporalio.activity.info().workflow_run_id

    if len(inputs.select) != 0:
        label = inputs.select[0].label
        saved_query = await get_saved_query(team, label)
        job = await start_job_modeling_run(team, workflow_id, workflow_run_id, saved_query)
    else:
        job = await start_job_modeling_run(team, workflow_id, workflow_run_id, None)

    return str(job.id)


@temporalio.activity.defn
async def start_run_activity(inputs: StartRunActivityInputs) -> None:
    """Activity that starts a run by updating statuses of associated models."""
    logger = await bind_temporal_worker_logger(inputs.team_id)

    try:
        async with asyncio.TaskGroup() as tg:
            for label in inputs.models_to_run:
                progress = None
                if label == inputs.root_model_id and len(inputs.models_to_run) > 1:
                    progress = "Updating upstream view(s)..."

                await logger.adebug(f"Updating saved query status for {label} to RUNNING")
                tg.create_task(
                    update_saved_query_status(
                        label,
                        DataWarehouseSavedQuery.Status.RUNNING,
                        None,
                        inputs.team_id,
                        progress=progress,
                    )
                )
    except* Exception:
        await logger.aexception("Failed to update saved query status when starting run")
        raise


@dataclasses.dataclass
class FinishRunActivityInputs:
    completed: list[str]
    failed: list[str]
    run_at: str
    team_id: int

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "run_at": self.run_at,
        }


@temporalio.activity.defn
async def finish_run_activity(inputs: FinishRunActivityInputs) -> None:
    """Activity that finishes a run by updating statuses of associated models."""
    logger = await bind_temporal_worker_logger(inputs.team_id)

    run_at = dt.datetime.fromisoformat(inputs.run_at)

    try:
        async with asyncio.TaskGroup() as tg:
            for label in inputs.completed:
                await logger.adebug(f"Updating saved query status for {label} to COMPLETED")
                tg.create_task(
                    update_saved_query_status(
                        label, DataWarehouseSavedQuery.Status.COMPLETED, run_at, inputs.team_id, progress=""
                    )
                )

            for label in inputs.failed:
                await logger.adebug(f"Updating saved query status for {label} to FAILED")
                tg.create_task(
                    update_saved_query_status(
                        label, DataWarehouseSavedQuery.Status.FAILED, None, inputs.team_id, progress=""
                    )
                )
    except* Exception:
        await logger.aexception("Failed to update saved query status when finishing run")
        raise


@dataclasses.dataclass
class CreateTableActivityInputs:
    models: list[str]
    team_id: int

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
        }


@temporalio.activity.defn
async def create_table_activity(inputs: CreateTableActivityInputs) -> None:
    """Activity that creates tables for a list of saved queries."""
    for model in inputs.models:
        await create_table_from_saved_query(model, inputs.team_id)


@temporalio.activity.defn
async def update_saved_query_status(
    label: str,
    status: DataWarehouseSavedQuery.Status,
    run_at: typing.Optional[dt.datetime],
    team_id: int,
    progress: typing.Optional[str] = None,
):
    filter_params: dict[str, int | str | uuid.UUID] = {"team_id": team_id}

    try:
        model_id = uuid.UUID(label)
        filter_params["id"] = model_id
    except ValueError:
        filter_params["name"] = label

    saved_query = await database_sync_to_async(
        DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(**filter_params).get
    )()

    if run_at:
        saved_query.last_run_at = run_at
    saved_query.status = status

    if progress is not None:
        saved_query.progress = progress

    await database_sync_to_async(saved_query.save)()


@dataclasses.dataclass
class CancelJobsActivityInputs:
    workflow_id: str
    workflow_run_id: str
    team_id: int


@dataclasses.dataclass
class FailJobsActivityInputs:
    job_id: str
    error: str
    team_id: int


@temporalio.activity.defn
async def cancel_jobs_activity(inputs: CancelJobsActivityInputs) -> None:
    """Activity to cancel data modeling jobs."""
    logger = await bind_temporal_worker_logger(inputs.team_id)

    await database_sync_to_async(
        DataModelingJob.objects.filter(workflow_id=inputs.workflow_id, workflow_run_id=inputs.workflow_run_id).update
    )(status=DataModelingJob.Status.CANCELLED)
    await logger.ainfo(
        "Cancelled data modeling jobs", workflow_id=inputs.workflow_id, workflow_run_id=inputs.workflow_run_id
    )


@temporalio.activity.defn
async def fail_jobs_activity(inputs: FailJobsActivityInputs) -> None:
    """Activity to fail data modeling jobs."""
    logger = await bind_temporal_worker_logger(inputs.team_id)
    job = await database_sync_to_async(DataModelingJob.objects.get)(id=inputs.job_id)

    await mark_job_as_failed(job, inputs.error, logger)


@dataclasses.dataclass
class RunWorkflowInputs:
    """Inputs to `RunWorkflow`.

    Attributes:
        team_id: The ID of the team we are running this for.
        select: A list of model selectors to define the models to run.
    """

    team_id: int
    select: list[Selector] = dataclasses.field(default_factory=list)

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
        }


@temporalio.activity.defn
async def run_single_model_activity(inputs: RunDagActivityInputs, label: str) -> str:
    """Runs a single materialized view node."""
    model = inputs.dag[label]
    try:
        await handle_model_ready(model, inputs.team_id, inputs.job_id)
        return "completed"
    except Exception:
        return "failed"


@temporalio.workflow.defn(name="data-modeling-run")
class RunWorkflow(PostHogWorkflow):
    """A Temporal Workflow to run PostHog data models.

    A model is defined by a label, a saved query that dictates how to select the data that
    makes up the model, and the path or paths to the model through all of its ancestors.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return RunWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: RunWorkflowInputs) -> Results:
        # Get the upstream DAG for the root model, the most downstream model in the DAG
        root_model_id = inputs.select[0].label

        upstream = await temporalio.workflow.execute_activity(
            get_upstream_dag_activity,
            args=(inputs.team_id, root_model_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )

        # Only consider materialized views that should be run
        mat_views = [node for node in upstream["nodes"] if node["type"] == "view" and node.get("sync_frequency")]
        mat_view_ids = {node["id"] for node in mat_views}

        jobs_map = await temporalio.workflow.execute_activity(
            create_jobs_for_materialized_views_activity,
            CreateJobsForMaterializedViewsActivityInputs(
                team_id=inputs.team_id, materialized_view_ids=list(mat_view_ids)
            ),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=1,
            ),
        )

        # Build full dependency graph
        all_deps: dict[str, set[str]] = collections.defaultdict(set)
        for edge in upstream["edges"]:
            all_deps[edge["target"]].add(edge["source"])

        # For each materialized view, find its materialized dependencies, traversing through non-materialized views
        dependencies: dict[str, set[str]] = {node_id: set() for node_id in mat_view_ids}
        dependents: dict[str, set[str]] = collections.defaultdict(set)
        for node_id in mat_view_ids:
            q = collections.deque(list(all_deps.get(node_id, [])))
            visited = set(q)
            while q:
                dep = q.popleft()
                if dep in mat_view_ids:
                    dependencies[node_id].add(dep)
                    dependents[dep].add(node_id)
                else:
                    # If the dependency is not a materialized view (e.g. another view, or a table), look at its dependencies
                    for grand_dep in all_deps.get(dep, []):
                        if grand_dep not in visited:
                            visited.add(grand_dep)
                            q.append(grand_dep)

        completed = set()
        failed = set()
        ancestor_failed = set()
        running: dict[str, asyncio.Task[str]] = {}
        ready = [node_id for node_id, deps in dependencies.items() if not deps]

        inputs.select[0] = dataclasses.replace(inputs.select[0], ancestors="ALL")
        build_dag_inputs = BuildDagActivityInputs(team_id=inputs.team_id, select=inputs.select)
        dag = await temporalio.workflow.execute_activity(
            build_dag_activity,
            build_dag_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            heartbeat_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=1,
            ),
        )

        run_at = dt.datetime.now(dt.UTC).isoformat()

        start_run_activity_inputs = StartRunActivityInputs(
            models_to_run=list(mat_view_ids), root_model_id=root_model_id, run_at=run_at, team_id=inputs.team_id
        )
        await temporalio.workflow.execute_activity(
            start_run_activity,
            start_run_activity_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=1,
            ),
        )

        while ready or running:
            for node_id in ready:
                run_dag_inputs = RunDagActivityInputs(team_id=inputs.team_id, dag=dag, job_id=jobs_map[node_id])
                fut = workflow.start_activity(
                    run_single_model_activity,
                    args=(run_dag_inputs, node_id),
                    start_to_close_timeout=dt.timedelta(hours=1),
                    heartbeat_timeout=dt.timedelta(minutes=5),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                )
                running[node_id] = fut
            ready = []

            if not running:
                break

            # Wait for any activity to complete
            await workflow.wait_condition(lambda: any(fut.done() for fut in running.values()))

            # Process all completed activities in this batch
            done_labels = [label for label, fut in running.items() if fut.done()]

            for done_label in done_labels:
                if done_label not in running:
                    continue  # Already handled as a descendant of a failed node

                fut = running.pop(done_label)
                is_success = False
                try:
                    status = await fut
                    if status == "completed":
                        is_success = True
                except temporalio.exceptions.ActivityError as e:
                    await logger.ainfo("Activity failed for model %s", done_label, error=str(e))

                if is_success:
                    completed.add(done_label)
                    # Check for new ready dependents
                    for dependent in dependents.get(done_label, set()):
                        if dependencies.get(dependent, set()).issubset(completed):
                            # It's ready, but might have been added to ready/running via another parent
                            if dependent not in running and dependent not in ready:
                                ready.append(dependent)
                else:
                    failed.add(done_label)
                    # Mark all descendants as ancestor_failed
                    q = collections.deque(list(dependents.get(done_label, set())))
                    while q:
                        descendant = q.popleft()
                        if descendant not in ancestor_failed:
                            ancestor_failed.add(descendant)
                            if descendant in running:
                                # We can't cancel, but we can untrack it to prevent it from being processed
                                del running[descendant]
                            q.extend(list(dependents.get(descendant, set())))

        # Create tables for all materialized views in the DAG
        await temporalio.workflow.execute_activity(
            create_table_activity,
            CreateTableActivityInputs(models=list(mat_view_ids), team_id=inputs.team_id),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=1,
            ),
        )

        await temporalio.workflow.execute_activity(
            finish_run_activity,
            FinishRunActivityInputs(
                completed=list(completed),
                failed=list(failed | ancestor_failed),
                run_at=temporalio.workflow.now().isoformat(),
                team_id=inputs.team_id,
            ),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
        )

        return Results(
            serialize_set(completed),
            serialize_set(failed),
            serialize_set(ancestor_failed),
        )


@temporalio.activity.defn
async def get_upstream_dag_activity(team_id: int, model_id: str) -> dict:
    return await database_sync_to_async(get_upstream_dag)(team_id, model_id, should_stringify_numerics=True)


def serialize_set(s):
    return {x.isoformat() if isinstance(x, dt.datetime) else x for x in s}
