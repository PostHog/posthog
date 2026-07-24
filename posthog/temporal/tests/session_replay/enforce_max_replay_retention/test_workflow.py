import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.enforce_max_replay_retention.types import EnforceMaxReplayRetentionInput
from posthog.temporal.session_replay.enforce_max_replay_retention.workflow import EnforceMaxReplayRetentionWorkflow


@pytest.mark.asyncio
async def test_workflow_runs_activity():
    activity_called_with: list[EnforceMaxReplayRetentionInput] = []

    @activity.defn(name="enforce-max-replay-retention")
    async def mock_enforce(input: EnforceMaxReplayRetentionInput) -> None:
        activity_called_with.append(input)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[EnforceMaxReplayRetentionWorkflow],
            activities=[mock_enforce],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                EnforceMaxReplayRetentionWorkflow.run,
                EnforceMaxReplayRetentionInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert len(activity_called_with) == 1
    assert activity_called_with[0].dry_run is True
