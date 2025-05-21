import asyncio
import collections.abc
import dataclasses
import datetime as dt
import enum
import itertools
import json
import re
import typing
import uuid

import os
import dlt
import dlt.common.data_types as dlt_data_types
import dlt.common.schema.typing as dlt_typing
import structlog
import temporalio.activity
import temporalio.common
import temporalio.exceptions
import temporalio.workflow
from deltalake import DeltaTable
from django.conf import settings
from dlt.common.libs.deltalake import get_delta_tables

from posthog.clickhouse.client.connection import Workload
from posthog.exceptions_capture import capture_exception
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.settings.base_variables import TEST
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.data_imports.util import prepare_s3_files_for_querying
from posthog.temporal.data_modeling.metrics import get_data_modeling_finished_metric
from posthog.warehouse.data_load.create_table import create_table_from_saved_query
from posthog.warehouse.models import DataWarehouseModelPath, DataWarehouseSavedQuery, DataWarehouseTable
from posthog.warehouse.models.data_modeling_job import DataModelingJob
from posthog.warehouse.util import database_sync_to_async

logger = structlog.get_logger()

# preserve casing since we are already coming from a sql dialect, we don't need to worry about normalizing
os.environ["SCHEMA__NAMING"] = "direct"

CLICKHOUSE_DLT_MAPPING: dict[str, dlt_data_types.TDataType] = {
    "UUID": "text",
    "String": "text",
    "DateTime64": "timestamp",
    "DateTime32": "timestamp",
    "DateTime": "timestamp",
    "Date": "date",
    "Date32": "date",
    "UInt8": "bigint",
    "UInt16": "bigint",
    "UInt32": "bigint",
    "UInt64": "bigint",
    "Float8": "double",
    "Float16": "double",
    "Float32": "double",
    "Float64": "double",
    "Int8": "bigint",
    "Int16": "bigint",
    "Int32": "bigint",
    "Int64": "bigint",
    "Tuple": "bigint",
    "Array": "complex",
    "Map": "complex",
    "Tuple": "complex",
    "Bool": "bool",
    "Decimal": "decimal",
}


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


@temporalio.activity.defn
async def run_dag_activity(inputs: RunDagActivityInputs) -> Results:
    """A Temporal activity to run a data modeling DAG.

    First, let's establish some definitions:
    * "Running a model" means:
      1. Executing the model's query (which is always a `SELECT` query).
      2. Save query results as a delta lake table in S3 ("materialize the results").
      Both steps are achieved with a dlt pipeline.
    * A model is considered "ready to run" if all of its ancestors have successfully ran
      already or if it has no ancestors.
    * PostHog tables (e.g. events, persons, sessions) are assumed to be always available
      and up to date, and thus can be considered to have ran successfully.

    This activity runs the following algorithm:
    1. Initialize 3 sets: completed, failed, and ancestor failed.
    2. Initialize a queue for models and statuses.
    3. Populate it with any models without parents set to status `ModelStatus.READY`.
    4. Start a loop.
    5. Pop an item from the queue and check the status:
       a. If it's `ModelStatus.READY`, schedule a task to run the model. Once the task is
          done, report back results by putting the same model with a
          `ModelStatus.COMPLETED` or `ModelStatus.FAILED` in the queue.
       b. If it's `ModelStatus.COMPLETED`, add the model to the completed set. Also, check
          if any of the model's children have become ready to run, by checking if all of
          their parents are in the completed set. Put any children that pass this check in
          status `ModelStatus.READY` in the queue.
       c. If it's `ModelStatus.FAILED`, add the model to the failed set. Also, add all
          descendants of the model that just failed to the ancestor failed set.
    6. If the number of models in the completed, failed, and ancestor failed sets is equal
       to the total number of models passed to this activity, exit the loop. Else, goto 5.
    """
    completed = set()
    ancestor_failed = set()
    failed = set()
    queue: asyncio.Queue[QueueMessage] = asyncio.Queue()

    for node in inputs.dag.values():
        if not node.parents:
            queue.put_nowait(QueueMessage(status=ModelStatus.READY, label=node.label))

    if queue.empty():
        raise asyncio.QueueEmpty()

    running_tasks = set()

    async with Heartbeater():
        while True:
            message = await queue.get()
            match message:
                case QueueMessage(status=ModelStatus.READY, label=label):
                    model = inputs.dag[label]
                    task = asyncio.create_task(handle_model_ready(model, inputs.team_id, queue))
                    running_tasks.add(task)
                    task.add_done_callback(running_tasks.discard)

                case QueueMessage(status=ModelStatus.COMPLETED, label=label):
                    node = inputs.dag[label]
                    completed.add(node.label)

                    to_queue = []
                    for child_label in node.children:
                        child_node = inputs.dag[child_label]

                        if completed >= child_node.parents:
                            to_queue.append(child_node)

                    task = asyncio.create_task(put_models_in_queue(to_queue, queue))
                    running_tasks.add(task)
                    task.add_done_callback(running_tasks.discard)

                    queue.task_done()

                case QueueMessage(status=ModelStatus.FAILED, label=label):
                    node = inputs.dag[label]
                    failed.add(node.label)

                    to_mark_as_ancestor_failed = list(node.children)
                    marked = set()
                    while to_mark_as_ancestor_failed:
                        to_mark = to_mark_as_ancestor_failed.pop()
                        ancestor_failed.add(to_mark)
                        marked.add(to_mark)

                        marked_node = inputs.dag[to_mark]
                        for child in marked_node.children:
                            if child in marked:
                                continue

                            to_mark_as_ancestor_failed.append(child)

                    queue.task_done()

                case message:
                    raise ValueError(f"Queue received an invalid message: {message}")

            if len(failed) + len(ancestor_failed) + len(completed) == len(inputs.dag):
                break

        return Results(completed, failed, ancestor_failed)


async def put_models_in_queue(models: collections.abc.Iterable[ModelNode], queue: asyncio.Queue[QueueMessage]) -> None:
    """Put models in queue.

    Intended to handle the queue put calls in the background to avoid blocking the main thread.
    We wait for all models to be put into the queue, concurrently, in a `asyncio.TaskGroup`.
    """

    async with asyncio.TaskGroup() as tg:
        for model in models:
            tg.create_task(queue.put(QueueMessage(status=ModelStatus.READY, label=model.label)))


class CHQueryErrorMemoryLimitExceeded(Exception):
    """Exception raised when a ClickHouse query exceeds memory limits."""

    pass


class CannotCoerceColumnException(Exception):
    """Exception raised when column types cannot be coerced."""

    pass


async def handle_model_ready(model: ModelNode, team_id: int, queue: asyncio.Queue[QueueMessage]) -> None:
    """Handle a model that is ready to run by materializing.

    After materializing is done, we can report back to the execution queue the result. If
    the model is not marked as `selected`, then it doesn't need to be materialized, and we
    can immediately put it back in the queue as `ModelStatus.COMPLETED`.

    Args:
        model: The model we are trying to run.
        team_id: The ID of the team who owns this model.
        queue: The execution queue where we will report back results.
    """

    try:
        if model.selected is True:
            team = await database_sync_to_async(Team.objects.get)(id=team_id)
            workflow_id = temporalio.activity.info().workflow_id
            workflow_run_id = temporalio.activity.info().workflow_run_id

            saved_query = await get_saved_query(team, model.label)
            job = await start_job_modeling_run(team, workflow_id, workflow_run_id, saved_query)
            key, delta_table, job_id = await materialize_model(model.label, team, saved_query, job)
    except CHQueryErrorMemoryLimitExceeded as err:
        await handle_error(job, model, queue, err, "Memory limit exceeded for model %s: %s")
    except CannotCoerceColumnException as err:
        await handle_error(job, model, queue, err, "Type coercion error for model %s: %s")
    except DataModelingCancelledException as err:
        await handle_cancelled(job, model, queue, err, "Data modeling run was cancelled for model %s: %s")
    except Exception as err:
        await handle_error(job, model, queue, err, "Failed to materialize model %s due to error: %s")
    else:
        await logger.ainfo("Materialized model %s", model.label)
        await queue.put(QueueMessage(status=ModelStatus.COMPLETED, label=model.label))
    finally:
        queue.task_done()


async def handle_error(
    job: DataModelingJob, model: ModelNode, queue: asyncio.Queue[QueueMessage], error: Exception, error_message: str
):
    if job:
        job.status = DataModelingJob.Status.FAILED
        job.error = str(error)
        await database_sync_to_async(job.save)()
    await queue.put(QueueMessage(status=ModelStatus.FAILED, label=model.label, error=str(error)))


async def handle_cancelled(
    job: DataModelingJob, model: ModelNode, queue: asyncio.Queue[QueueMessage], error: Exception, error_message: str
):
    if job:
        job.status = DataModelingJob.Status.CANCELLED
        job.error = str(error)
        await database_sync_to_async(job.save)()
    await queue.put(QueueMessage(status=ModelStatus.FAILED, label=model.label, error=str(error)))


async def start_job_modeling_run(
    team: Team, workflow_id: str, workflow_run_id: str, saved_query: DataWarehouseSavedQuery
) -> DataModelingJob:
    """Create a DataModelingJob record in an async-safe way."""
    job_create = database_sync_to_async(DataModelingJob.objects.create)
    return await job_create(
        team=team,
        saved_query=saved_query,
        status=DataModelingJob.Status.RUNNING,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        created_by_id=saved_query.created_by_id,
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
    model_label: str, team: Team, saved_query: DataWarehouseSavedQuery, job: DataModelingJob
) -> tuple[str, DeltaTable, uuid.UUID]:
    """Materialize a given model by running its query in a dlt pipeline.

    Arguments:
        model_label: A label representing the ID or the name of the model to materialize.
            If it's a valid UUID, then we will assume it's the ID, otherwise we'll assume
            it is the model's name.
        team: The team the model belongs to.
        saved_query: The saved query to materialize.
        job: The DataModelingJob record for this run that tracks the lifecycle and rows of the run.
    """

    query_columns = saved_query.columns
    if not query_columns:
        query_columns = await database_sync_to_async(saved_query.get_columns)()

    table_columns: dlt_typing.TTableSchemaColumns = {}
    for column_name, column_info in query_columns.items():
        clickhouse_type = column_info["clickhouse"]
        nullable = False

        if nullable_match := re.match(NullablePattern, clickhouse_type):
            clickhouse_type = nullable_match.group(1)
            nullable = True

        clickhouse_type = re.sub(r"\(.+\)+", "", clickhouse_type)

        data_type: dlt_data_types.TDataType = CLICKHOUSE_DLT_MAPPING[clickhouse_type]
        column_schema: dlt_typing.TColumnSchema = {
            "data_type": data_type,
            "nullable": nullable,
        }
        table_columns[column_name] = column_schema

    hogql_query = saved_query.query["query"]
    destination = get_dlt_destination()
    pipeline = dlt.pipeline(
        pipeline_name=f"materialize_model_{model_label}",
        destination=destination,
        dataset_name=f"team_{team.pk}_model_{model_label}",
        refresh="drop_sources",
    )

    try:
        _ = await asyncio.to_thread(pipeline.run, hogql_table(hogql_query, team, saved_query.name, table_columns))
    except Exception as e:
        error_message = str(e)
        if "Query exceeds memory limits" in error_message:
            saved_query.latest_error = error_message
            await database_sync_to_async(saved_query.save)()
            await mark_job_as_failed(job, error_message)
            raise CHQueryErrorMemoryLimitExceeded(
                f"Query for model {model_label} exceeds memory limits. Try reducing its scope by changing the time range."
            ) from e

        elif "Cannot coerce type" in error_message:
            saved_query.latest_error = error_message
            await database_sync_to_async(saved_query.save)()
            await mark_job_as_failed(job, error_message)

            raise CannotCoerceColumnException(f"Type coercion error in model {model_label}: {error_message}") from e
        else:
            saved_query.latest_error = f"Failed to materialize model {model_label}"
            error_message = "Your query failed to materialize. If this query ran for a long time, try optimizing it."
            await database_sync_to_async(saved_query.save)()
            await mark_job_as_failed(job, error_message)
            raise Exception(f"Failed to materialize model {model_label}: {error_message}") from e

    data_modeling_job = await database_sync_to_async(DataModelingJob.objects.get)(id=job.id)
    if data_modeling_job.status == DataModelingJob.Status.CANCELLED:
        raise DataModelingCancelledException("Data modeling run was cancelled")

    tables = get_delta_tables(pipeline)
    for table in tables.values():
        table.optimize.compact()
        table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)

        file_uris = table.file_uris()

        prepare_s3_files_for_querying(saved_query.folder_path, saved_query.name, file_uris, True)

    if not tables:
        saved_query.latest_error = f"No tables were created by pipeline for model {model_label}"
        await database_sync_to_async(saved_query.save)()
        raise Exception(f"No tables were created by pipeline for model {model_label}")

    key, delta_table = tables.popitem()

    # Count rows and update both DataWarehouseTable and DataModelingJob
    row_count = count_pipeline_rows(pipeline)
    await update_table_row_count(saved_query, row_count)

    # Update the job record with the row count and completed status
    job.rows_materialized = row_count
    job.status = DataModelingJob.Status.COMPLETED
    job.last_run_at = dt.datetime.now(dt.UTC)
    await database_sync_to_async(job.save)()

    return (key, delta_table, job.id)


async def mark_job_as_failed(job: DataModelingJob, error_message: str) -> None:
    """
    Mark DataModelingJob as failed
    """
    job.status = DataModelingJob.Status.FAILED
    job.error = error_message
    await database_sync_to_async(job.save)()


def count_pipeline_rows(pipeline: dlt.Pipeline) -> int:
    """
    Count the number of rows written in a dlt pipeline
    """
    row_counts = pipeline.last_trace.last_normalize_info.row_counts
    filtered_rows = dict(filter(lambda pair: not pair[0].startswith("_dlt"), row_counts.items()))
    return sum(filtered_rows.values())


async def update_table_row_count(saved_query: DataWarehouseSavedQuery, row_count: int) -> None:
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


@dlt.source(max_table_nesting=0)
def hogql_table(query: str, team: Team, table_name: str, table_columns: dlt_typing.TTableSchemaColumns):
    """A dlt source representing a HogQL table given by a HogQL query."""

    async def get_hogql_rows():
        settings = HogQLGlobalSettings(
            max_execution_time=60 * 20, max_memory_usage=180 * 1000 * 1000 * 1000
        )  # 20 mins, 180gb, 2x execution_time, 4x max_memory_usage as the /query endpoint async workers

        # Pass the query_type parameter to influence tags in a thread safe way
        response = await asyncio.to_thread(
            execute_hogql_query,
            query,
            team,
            settings=settings,
            limit_context=LimitContext.SAVED_QUERY,
            workload=Workload.OFFLINE,
            query_type="materialization",
        )

        if not response.columns:
            raise EmptyHogQLResponseColumnsError()

        columns: list[str] = response.columns

        for row in response.results:
            yield dict(zip(columns, row))

    yield dlt.resource(
        get_hogql_rows,
        name="hogql_table",
        table_name=table_name,
        table_format="delta",
        write_disposition="replace",
        columns=table_columns,
    )


def get_dlt_destination():
    if TEST:
        credentials = {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }
    else:
        credentials = {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    return dlt.destinations.filesystem(
        credentials=credentials,
        bucket_url=settings.BUCKET_URL,  # type: ignore
        layout="modeling/{table_name}/{load_id}.{file_id}.{ext}",
    )


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
    dag: DAG
    run_at: str
    team_id: int

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "run_at": self.run_at,
        }


@temporalio.activity.defn
async def start_run_activity(inputs: StartRunActivityInputs) -> None:
    """Activity that starts a run by updating statuses of associated models."""

    try:
        async with asyncio.TaskGroup() as tg:
            for label, model in inputs.dag.items():
                if model.selected is False:
                    continue

                tg.create_task(
                    update_saved_query_status(label, DataWarehouseSavedQuery.Status.RUNNING, None, inputs.team_id)
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
    run_at = dt.datetime.fromisoformat(inputs.run_at)

    try:
        async with asyncio.TaskGroup() as tg:
            for label in inputs.completed:
                tg.create_task(
                    update_saved_query_status(label, DataWarehouseSavedQuery.Status.COMPLETED, run_at, inputs.team_id)
                )

            for label in inputs.failed:
                tg.create_task(
                    update_saved_query_status(label, DataWarehouseSavedQuery.Status.FAILED, None, inputs.team_id)
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


async def update_saved_query_status(
    label: str, status: DataWarehouseSavedQuery.Status, run_at: typing.Optional[dt.datetime], team_id: int
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

    await database_sync_to_async(saved_query.save)()


@dataclasses.dataclass
class CancelJobsActivityInputs:
    workflow_id: str
    workflow_run_id: str
    team_id: int


@dataclasses.dataclass
class FailJobsActivityInputs:
    workflow_id: str
    workflow_run_id: str
    error: str


@temporalio.activity.defn
async def cancel_jobs_activity(inputs: CancelJobsActivityInputs) -> None:
    """Activity to cancel data modeling jobs."""
    await database_sync_to_async(
        DataModelingJob.objects.filter(workflow_id=inputs.workflow_id, workflow_run_id=inputs.workflow_run_id).update
    )(status=DataModelingJob.Status.CANCELLED)
    await logger.ainfo(
        "Cancelled data modeling jobs", workflow_id=inputs.workflow_id, workflow_run_id=inputs.workflow_run_id
    )


@temporalio.activity.defn
async def fail_jobs_activity(inputs: FailJobsActivityInputs) -> None:
    """Activity to fail data modeling jobs."""
    job = await database_sync_to_async(DataModelingJob.objects.get)(
        workflow_id=inputs.workflow_id, workflow_run_id=inputs.workflow_run_id
    )

    await mark_job_as_failed(job, inputs.error)


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

        start_run_activity_inputs = StartRunActivityInputs(dag=dag, run_at=run_at, team_id=inputs.team_id)
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

        # Run the DAG
        run_model_activity_inputs = RunDagActivityInputs(team_id=inputs.team_id, dag=dag)
        try:
            results = await temporalio.workflow.execute_activity(
                run_dag_activity,
                run_model_activity_inputs,
                start_to_close_timeout=dt.timedelta(hours=1),
                heartbeat_timeout=dt.timedelta(minutes=1),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=1,
                ),
                cancellation_type=temporalio.workflow.ActivityCancellationType.TRY_CANCEL,
            )
        except temporalio.exceptions.ActivityError as e:
            if isinstance(e.cause, temporalio.exceptions.CancelledError):
                workflow_id = temporalio.workflow.info().workflow_id
                workflow_run_id = temporalio.workflow.info().run_id
                try:
                    await temporalio.workflow.execute_activity(
                        cancel_jobs_activity,
                        CancelJobsActivityInputs(
                            workflow_id=workflow_id, workflow_run_id=workflow_run_id, team_id=inputs.team_id
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=temporalio.common.RetryPolicy(
                            maximum_attempts=3,
                        ),
                    )
                except Exception as cancel_err:
                    capture_exception(cancel_err)
                    temporalio.workflow.logger.error(f"Failed to cancel jobs: {str(cancel_err)}")
                    raise
                raise

            capture_exception(e)
            temporalio.workflow.logger.error(f"Activity failed during model run: {str(e)}")

            workflow_id = temporalio.workflow.info().workflow_id
            workflow_run_id = temporalio.workflow.info().run_id

            await temporalio.workflow.execute_activity(
                fail_jobs_activity,
                FailJobsActivityInputs(workflow_id=workflow_id, workflow_run_id=workflow_run_id, error=str(e)),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=3,
                ),
            )
            raise

        completed, failed, ancestor_failed = results

        # publish metrics
        if failed or ancestor_failed:
            get_data_modeling_finished_metric(status="failed").add(1)
        elif completed:
            get_data_modeling_finished_metric(status="completed").add(1)

        selected_labels = [selector.label for selector in inputs.select]
        create_table_activity_inputs = CreateTableActivityInputs(
            models=[label for label in completed if label in selected_labels], team_id=inputs.team_id
        )
        await temporalio.workflow.execute_activity(
            create_table_activity,
            create_table_activity_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=1,
            ),
        )

        finish_run_activity_inputs = FinishRunActivityInputs(
            completed=[label for label in completed if dag[label].selected is True],
            failed=[label for label in itertools.chain(failed, ancestor_failed) if dag[label].selected is True],
            run_at=run_at,
            team_id=inputs.team_id,
        )
        await temporalio.workflow.execute_activity(
            finish_run_activity,
            finish_run_activity_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=1,
            ),
        )

        return results
