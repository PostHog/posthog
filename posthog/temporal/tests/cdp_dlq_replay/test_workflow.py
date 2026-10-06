import uuid
from typing import Any

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.cdp_dlq_replay.workflow import (
    LIST_PARTITIONS_ACTIVITY,
    REPLAY_PARTITION_ACTIVITY,
    CdpDlqReplayInputs,
    CdpDlqReplayWorkflow,
)


async def _run(replay: Any, skip_unreplayable: bool = False) -> Any:
    @activity.defn(name=LIST_PARTITIONS_ACTIVITY)
    async def list_partitions() -> list[int]:
        return [0, 1, 2]

    @activity.defn(name=REPLAY_PARTITION_ACTIVITY)
    async def replay_partition(input: dict[str, Any]) -> dict[str, Any]:
        return replay(input)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[CdpDlqReplayWorkflow],
            activities=[list_partitions, replay_partition],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                CdpDlqReplayWorkflow.run,
                CdpDlqReplayInputs(skip_unreplayable=skip_unreplayable, task_queue=task_queue),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("skip_unreplayable", [False, True])
async def test_replays_every_partition_and_adds_up_the_results(skip_unreplayable):
    calls: list[dict[str, Any]] = []

    def replay(input: dict[str, Any]) -> dict[str, Any]:
        calls.append(input)
        return {"partition": input["partition"], "records_read": 5, "records_skipped": 1, "invocations_queued": 3}

    result = await _run(replay, skip_unreplayable)

    assert sorted(call["partition"] for call in calls) == [0, 1, 2]
    assert all(call["skip_unreplayable"] is skip_unreplayable for call in calls)
    assert (result.records_read, result.records_skipped, result.invocations_queued) == (15, 3, 9)


@pytest.mark.asyncio
async def test_a_record_that_cannot_be_replayed_fails_the_run_with_its_offset():
    def replay(input: dict[str, Any]) -> dict[str, Any]:
        if input["partition"] == 1:
            raise ApplicationError("Partition 1 offset 7 cannot be replayed: still fails", non_retryable=True)
        return {"partition": input["partition"], "records_read": 1, "records_skipped": 0, "invocations_queued": 1}

    with pytest.raises(WorkflowFailureError) as failure:
        await _run(replay)

    activity_error = failure.value.cause
    assert isinstance(activity_error, ActivityError)
    assert "offset 7" in str(activity_error.cause)
