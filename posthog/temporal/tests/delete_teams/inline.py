"""Run the team/org deletion Temporal workflows inline for tests that need real side effects.

The API deletion endpoints hand off to Temporal via ``start_delete_project_data_workflow`` /
``start_delete_organization_workflow``. Tests that assert on the *effects* of deletion (batch
exports removed, schedules deleted, persons cleaned up, records gone) need those workflows to run
to completion synchronously. ``execute_deletion_workflows_inline`` patches both dispatch helpers to
execute the corresponding workflow on an in-process time-skipping ``WorkflowEnvironment`` with the
real activities, so the side effects land in the test's (committed) database.

Only ``queue_recording_deletions_activity`` is stubbed — it starts a separate recording-deletion
workflow on the external cluster, which is out of scope for these tests and covered elsewhere.

Callers MUST run in a non-atomic test case (``NonAtomicBaseTest`` / ``transaction=True``); the
activities run on a worker thread pool with their own connections and cannot see data held open in
an uncommitted transaction.
"""

import uuid
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from unittest.mock import patch

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.delete_teams import ACTIVITIES as REAL_ACTIVITIES
from posthog.temporal.delete_teams.activities import (
    queue_recording_deletions_activity as real_queue_recording_deletions_activity,
)
from posthog.temporal.delete_teams.types import (
    DeleteOrganizationWorkflowInputs,
    DeleteProjectDataWorkflowInputs,
    TeamDataActivityInputs,
)
from posthog.temporal.delete_teams.workflows import (
    DeleteOrganizationWorkflow,
    DeleteProjectDataWorkflow,
    DeleteTeamsDataWorkflow,
)

WORKFLOWS = [DeleteTeamsDataWorkflow, DeleteProjectDataWorkflow, DeleteOrganizationWorkflow]

# Activities swapped for no-op stubs in the inline worker, matched by object identity so the swap
# stays correct regardless of how the Temporal SDK derives the registered activity name.
_STUBBED_ACTIVITIES = {real_queue_recording_deletions_activity}


def _inline_activities() -> list:
    @activity.defn(name="queue_recording_deletions_activity")
    async def queue_recording_deletions_activity(inputs: TeamDataActivityInputs) -> None:
        pass

    real = [fn for fn in REAL_ACTIVITIES if fn not in _STUBBED_ACTIVITIES]
    return [*real, queue_recording_deletions_activity]


async def _execute(workflow_run, inputs) -> None:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=WORKFLOWS,
            activities=_inline_activities(),
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(workflow_run, inputs, id=str(uuid.uuid4()), task_queue=task_queue)


def _run_delete_project_data(*, team_ids: list[int], project_id: int | None, user_id: int, project_name: str) -> None:
    inputs = DeleteProjectDataWorkflowInputs(
        team_ids=team_ids, project_id=project_id, user_id=user_id, project_name=project_name
    )
    asyncio.run(_execute(DeleteProjectDataWorkflow.run, inputs))


def _run_delete_organization(
    *, team_ids: list[int], organization_id: str, user_id: int, organization_name: str, project_names: list[str]
) -> None:
    inputs = DeleteOrganizationWorkflowInputs(
        team_ids=team_ids,
        organization_id=organization_id,
        user_id=user_id,
        organization_name=organization_name,
        project_names=project_names,
    )
    asyncio.run(_execute(DeleteOrganizationWorkflow.run, inputs))


@contextmanager
def execute_deletion_workflows_inline() -> Iterator[None]:
    """Patch the deletion dispatch helpers to run their workflows to completion synchronously."""
    with (
        patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow", _run_delete_project_data),
        patch("posthog.temporal.delete_teams.dispatch.start_delete_organization_workflow", _run_delete_organization),
    ):
        yield
