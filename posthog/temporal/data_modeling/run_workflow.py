import asyncio
import collections
import dataclasses
import datetime as dt
import enum
import functools

import temporalio.activity
import temporalio.common
import temporalio.workflow

from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.warehouse.models import DataWarehouseModelPath
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
                    task = asyncio.create_task(handle_materialize_model(model_label, queue))
                    running_tasks.add(task)
                    task.add_done_callback(running_tasks.discard)

                case QueueMessage(status=ModelStatus.FAILED, model_label=model_label):
                    node = inputs.nodes_map[model_label]
                    failed.add(node.label)

                    for child_label in node.children:
                        ancestor_failed.add(child_label)

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


async def handle_materialize_model(model_label: str, queue: asyncio.Queue):
    try:
        await materialize_model(model_label)
    except Exception:
        await queue.put(QueueMessage(status=ModelStatus.FAILED, model_label=model_label))
    else:
        await queue.put(QueueMessage(status=ModelStatus.COMPLETED, model_label=model_label))
    finally:
        queue.task_done()


async def materialize_model(model):
    pass


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
