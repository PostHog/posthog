import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.backfill_group_type_created_at.types import (
    ApplyBackfillInput,
    BackfillGroupTypeCreatedAtInput,
    PlanBackfillInput,
)
from posthog.temporal.backfill_group_type_created_at.workflows import BackfillGroupTypeCreatedAtWorkflow

pytestmark = pytest.mark.persons_db_direct

TEST_TEAM_ID = 12345
TEST_PROJECT_ID = 12345
SAMPLE_UPDATES = [
    {
        "group_type": "customer",
        "group_type_index": 0,
        "current_created_at": "2026-05-31T22:33:00+00:00",
        "new_created_at": "2026-05-12T00:00:00+00:00",
    }
]


@pytest.mark.asyncio
async def test_workflow_applies_planned_updates():
    applied_updates = None

    @activity.defn(name="plan-group-type-created-at-backfill")
    async def plan_mocked(input: PlanBackfillInput) -> dict:
        assert input.team_id == TEST_TEAM_ID
        return {
            "team_id": TEST_TEAM_ID,
            "project_id": TEST_PROJECT_ID,
            "team_ids_in_project": [TEST_TEAM_ID],
            "updates": SAMPLE_UPDATES,
            "skipped": [],
        }

    @activity.defn(name="apply-group-type-created-at-backfill")
    async def apply_mocked(input: ApplyBackfillInput) -> dict:
        nonlocal applied_updates
        assert input.project_id == TEST_PROJECT_ID
        applied_updates = input.updates
        return {"updated": len(input.updates)}

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[BackfillGroupTypeCreatedAtWorkflow],
            activities=[plan_mocked, apply_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                BackfillGroupTypeCreatedAtWorkflow.run,
                BackfillGroupTypeCreatedAtInput(team_id=TEST_TEAM_ID, dry_run=False),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert result["team_id"] == TEST_TEAM_ID
    assert result["project_id"] == TEST_PROJECT_ID
    assert result["dry_run"] is False
    assert result["updated"] == 1
    assert result["updates"] == SAMPLE_UPDATES
    assert applied_updates == SAMPLE_UPDATES


@pytest.mark.asyncio
async def test_workflow_dry_run_does_not_apply():
    @activity.defn(name="plan-group-type-created-at-backfill")
    async def plan_mocked(input: PlanBackfillInput) -> dict:
        return {
            "team_id": TEST_TEAM_ID,
            "project_id": TEST_PROJECT_ID,
            "team_ids_in_project": [TEST_TEAM_ID],
            "updates": SAMPLE_UPDATES,
            "skipped": [],
        }

    @activity.defn(name="apply-group-type-created-at-backfill")
    async def apply_mocked(input: ApplyBackfillInput) -> dict:
        raise AssertionError("Should not be called in dry run mode")

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[BackfillGroupTypeCreatedAtWorkflow],
            activities=[plan_mocked, apply_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                BackfillGroupTypeCreatedAtWorkflow.run,
                BackfillGroupTypeCreatedAtInput(team_id=TEST_TEAM_ID, dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert result["dry_run"] is True
    assert result["updated"] == 0
    assert result["updates"] == SAMPLE_UPDATES


@pytest.mark.asyncio
async def test_workflow_skips_apply_when_nothing_to_update():
    @activity.defn(name="plan-group-type-created-at-backfill")
    async def plan_mocked(input: PlanBackfillInput) -> dict:
        return {
            "team_id": TEST_TEAM_ID,
            "project_id": TEST_PROJECT_ID,
            "team_ids_in_project": [TEST_TEAM_ID],
            "updates": [],
            "skipped": [{"group_type_index": 0, "group_type": "customer", "reason": "created_at already null"}],
        }

    @activity.defn(name="apply-group-type-created-at-backfill")
    async def apply_mocked(input: ApplyBackfillInput) -> dict:
        raise AssertionError("Should not be called when there are no updates")

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[BackfillGroupTypeCreatedAtWorkflow],
            activities=[plan_mocked, apply_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                BackfillGroupTypeCreatedAtWorkflow.run,
                BackfillGroupTypeCreatedAtInput(team_id=TEST_TEAM_ID, dry_run=False),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert result["updated"] == 0
    assert result["updates"] == []
    assert len(result["skipped"]) == 1


def test_workflow_parse_inputs():
    result = BackfillGroupTypeCreatedAtWorkflow.parse_inputs(['{"team_id": 12345, "dry_run": true}'])
    assert result.team_id == 12345
    assert result.dry_run is True

    result = BackfillGroupTypeCreatedAtWorkflow.parse_inputs(['{"team_id": 99999}'])
    assert result.team_id == 99999
    assert result.dry_run is False
