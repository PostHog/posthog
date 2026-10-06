import uuid
from typing import Any

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.cdp_dlq_replay.workflow import REPLAY_ACTIVITY, CdpDlqReplayInputs, CdpDlqReplayWorkflow


async def _run(replay: Any, skip_unreplayable: bool = False) -> Any:
    @activity.defn(name=REPLAY_ACTIVITY)
    async def replay_activity(input: dict[str, Any]) -> dict[str, Any]:
        return replay(input)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[CdpDlqReplayWorkflow],
            activities=[replay_activity],
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
async def test_passes_the_skip_flag_and_returns_the_totals(skip_unreplayable):
    calls: list[dict[str, Any]] = []
    skipped = [{"partition": 1, "offset": 7, "error": "will never parse"}]

    def replay(input: dict[str, Any]) -> dict[str, Any]:
        calls.append(input)
        return {"records_read": 5, "records_skipped": 1, "invocations_queued": 3, "skipped": skipped}

    result = await _run(replay, skip_unreplayable)

    assert calls == [{"skip_unreplayable": skip_unreplayable}]
    assert (result.records_read, result.records_skipped, result.invocations_queued) == (5, 1, 3)
    assert result.skipped == skipped


@pytest.mark.asyncio
async def test_a_record_that_cannot_be_replayed_fails_the_run_with_its_offset():
    def replay(input: dict[str, Any]) -> dict[str, Any]:
        raise ApplicationError("Partition 1 offset 7 cannot be replayed: still fails", non_retryable=True)

    with pytest.raises(WorkflowFailureError) as failure:
        await _run(replay)

    activity_error = failure.value.cause
    assert isinstance(activity_error, ActivityError)
    assert "offset 7" in str(activity_error.cause)
