import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.gemini_cleanup_sweep.constants import WORKFLOW_NAME
from posthog.temporal.session_replay.gemini_cleanup_sweep.types import CleanupSweepInputs, CleanupSweepResult
from posthog.temporal.session_replay.gemini_cleanup_sweep.workflow import GeminiFileCleanupSweepWorkflow


@pytest.mark.asyncio
async def test_workflow_returns_activity_result_as_dict():
    @activity.defn(name="sweep_gemini_files_activity")
    async def sweep_mocked(inputs: CleanupSweepInputs) -> CleanupSweepResult:
        return CleanupSweepResult(
            listed=42,
            deleted=10,
            skipped_running=5,
            skipped_too_young=20,
            skipped_unrecognized_prefix=2,
            skipped_no_name=1,
            skipped_temporal_error=1,
            delete_failed=1,
            hit_max_files_cap=False,
        )

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[GeminiFileCleanupSweepWorkflow],
            activities=[sweep_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                CleanupSweepInputs(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result == {
        "listed": 42,
        "deleted": 10,
        "skipped_running": 5,
        "skipped_too_young": 20,
        "skipped_unrecognized_prefix": 2,
        "skipped_no_name": 1,
        "skipped_temporal_error": 1,
        "delete_failed": 1,
        "hit_max_files_cap": False,
    }
