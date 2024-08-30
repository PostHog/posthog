import asyncio
import collections
import dataclasses
import datetime as dt
import enum
import functools
import uuid

import dlt
import dlt.extract
import temporalio.activity
import temporalio.common
import temporalio.workflow
from django.conf import settings

from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.settings.base_variables import TEST
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.warehouse.models import DataWarehouseModelPath, DataWarehouseSavedQuery
from posthog.warehouse.util import database_sync_to_async


@dataclasses.dataclass(frozen=True)
class ModelNode:
    label: str
    children: set[str]
    parents: set[str]


@dataclasses.dataclass
class RunModelActivityInputs:
    team_id: int
    nodes_map: dict[str, ModelNode]


class ModelStatus(enum.StrEnum):
    COMPLETED = "Completed"
    FAILED = "Failed"
    READY = "Ready"


@dataclasses.dataclass
class QueueMessage:
    status: ModelStatus
    model_label: str


Results = collections.namedtuple("Results", ("completed", "failed", "ancestor_failed"))


@temporalio.activity.defn
async def run_model_activity(inputs: RunModelActivityInputs) -> Results:
    completed = set()
    ancestor_failed = set()
    failed = set()
    queue = asyncio.Queue()

    for node in inputs.nodes_map.values():
        if not node.parents:
            queue.put_nowait(QueueMessage(status=ModelStatus.READY, model_label=node.label))

    if queue.empty():
        raise asyncio.QueueEmpty()

    running_tasks = set()

    async with Heartbeater():
        while True:
            message = await queue.get()

            match message:
                case QueueMessage(status=ModelStatus.READY, model_label=model_label):
                    task = asyncio.create_task(handle_materialize_model(model_label, inputs.team_id, queue))
                    running_tasks.add(task)
                    task.add_done_callback(running_tasks.discard)

                case QueueMessage(status=ModelStatus.FAILED, model_label=model_label):
                    node = inputs.nodes_map[model_label]
                    failed.add(node.label)

                    to_mark_as_ancestor_failed = list(node.children)
                    marked = set()
                    while to_mark_as_ancestor_failed:
                        to_mark = to_mark_as_ancestor_failed.pop()
                        ancestor_failed.add(to_mark)
                        marked.add(to_mark)

                        marked_node = inputs.nodes_map[to_mark]
                        for child in marked_node.children:
                            if child in marked:
                                continue

                            to_mark_as_ancestor_failed.append(child)

                    queue.task_done()

                case QueueMessage(status=ModelStatus.COMPLETED, model_label=model_label):
                    node = inputs.nodes_map[model_label]
                    completed.add(node.label)

                    for child_label in node.children:
                        child_node = inputs.nodes_map[child_label]

                        if completed >= child_node.parents:
                            await queue.put(QueueMessage(status=ModelStatus.READY, model_label=child_label))

                    queue.task_done()

                case message:
                    raise ValueError(message)

            if len(failed) + len(ancestor_failed) + len(completed) == len(inputs.nodes_map):
                break

        return Results(completed, failed, ancestor_failed)


async def handle_materialize_model(model_label: str, team_id: int, queue: asyncio.Queue):
    try:
        team = await database_sync_to_async(Team.objects.get)(id=team_id)
        hogql_db = await database_sync_to_async(create_hogql_database)(team_id=team_id, team_arg=team)
        posthog_tables = hogql_db.get_posthog_tables()

        if model_label not in posthog_tables:
            await materialize_model(model_label, team)
    except Exception:
        await queue.put(QueueMessage(status=ModelStatus.FAILED, model_label=model_label))
    else:
        await queue.put(QueueMessage(status=ModelStatus.COMPLETED, model_label=model_label))
    finally:
        queue.task_done()


async def materialize_model(model_label: str, team: Team):
    saved_query = await database_sync_to_async(
        DataWarehouseSavedQuery.objects.filter(team=team, id=uuid.UUID(model_label)).get
    )()
    hogql_query = saved_query.query["query"]

    destination = get_dlt_destination()
    pipeline = dlt.pipeline(
        pipeline_name=f"materialize_model_{model_label}",
        destination=destination,
        dataset_name=f"team_{team.pk}_model_{model_label}",
    )
    await asyncio.to_thread(pipeline.run, get_hogql_rows(hogql_query, team))


@dlt.resource
async def get_hogql_rows(query: str, team: Team):
    rows = await asyncio.to_thread(execute_hogql_query, query, team)

    for row in rows:
        yield row


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


@dataclasses.dataclass
class SelectMatchingPaths:
    team_id: int
    select: list[str] = dataclasses.field(default_factory=list)


@temporalio.activity.defn
async def select_matching_paths(inputs: SelectMatchingPaths) -> list[str]:
    async with Heartbeater():

        def str_or(select_left, select_right):
            return f"{select_left} | {select_right}"

        ltxtquery = functools.reduce(str_or, inputs.select)

        matching_paths = await database_sync_to_async(
            DataWarehouseModelPath.objects.filter(team_id=inputs.team_id, path__ltxtquery=ltxtquery).all
        )()
        return matching_paths


@dataclasses.dataclass
class RunWorkflowInputs:
    team_id: int
    select: list[str] = dataclasses.field(default_factory=list)


@temporalio.workflow.defn(name="data-models-run")
class RunWorkflow(PostHogWorkflow):
    """A Temporal Workflow to run PostHog data models."""

    @temporalio.workflow.run
    async def run(self, inputs: RunWorkflowInputs) -> Results:
        select_matching_paths_inputs = SelectMatchingPaths(team_id=inputs.team_id, select=inputs.select)
        matching_paths = await temporalio.workflow.execute_activity(
            select_matching_paths,
            select_matching_paths_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
            ),
        )

        nodes_map = {}

        for matching_path in matching_paths:
            label_iterable = matching_path.split(".")

            for index, label in enumerate(label_iterable):
                if label not in nodes_map:
                    nodes_map[label] = ModelNode(label=label, children=set(), parents=set())

                node = nodes_map[label]

                if index > 0:
                    child_node = label_iterable[index - 1]
                    node.children.add(child_node)

                if index < len(label_iterable) - 1:
                    parent_node = label_iterable[index + 1]
                    node.parents.add(parent_node)

        run_model_activity_inputs = RunModelActivityInputs(team_id=inputs.team_id, nodes_map=nodes_map)
        results = await temporalio.workflow.execute_activity(
            run_model_activity,
            run_model_activity_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=0,
            ),
        )

        return results
