import uuid

import pytest
from unittest.mock import AsyncMock

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.summarization_sweep.constants import WORKFLOW_NAME
from posthog.temporal.session_replay.summarization_sweep.models import (
    DeleteTeamScheduleInput,
    FindSessionsInput,
    FindSessionsResult,
    SummarizeTeamSessionsInputs,
)
from posthog.temporal.session_replay.summarization_sweep.workflow import SummarizeTeamSessionsWorkflow


@pytest.mark.asyncio
async def test_workflow_self_deletes_schedule_when_team_disabled():
    delete_calls: list[int] = []

    @activity.defn(name="find_sessions_for_team_activity")
    async def find_sessions_mocked(inputs: FindSessionsInput) -> FindSessionsResult:
        return FindSessionsResult(team_id=inputs.team_id, team_disabled=True)

    @activity.defn(name="delete_team_schedule_activity")
    async def delete_schedule_mocked(inputs: DeleteTeamScheduleInput) -> None:
        delete_calls.append(inputs.team_id)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SummarizeTeamSessionsWorkflow],
            activities=[find_sessions_mocked, delete_schedule_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                SummarizeTeamSessionsInputs(team_id=42),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert delete_calls == [42]
    assert result == {
        "team_id": 42,
        "team_disabled": True,
        "workflows_started": 0,
        "workflows_skipped_already_running": 0,
        "dry_run": False,
    }


@pytest.mark.asyncio
async def test_workflow_noop_when_no_sessions():
    delete_mock = AsyncMock()

    @activity.defn(name="find_sessions_for_team_activity")
    async def find_sessions_mocked(inputs: FindSessionsInput) -> FindSessionsResult:
        return FindSessionsResult(team_id=inputs.team_id, session_ids=[], user_id=None)

    @activity.defn(name="delete_team_schedule_activity")
    async def delete_schedule_mocked(inputs: DeleteTeamScheduleInput) -> None:
        await delete_mock(inputs)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SummarizeTeamSessionsWorkflow],
            activities=[find_sessions_mocked, delete_schedule_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                SummarizeTeamSessionsInputs(team_id=42),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    delete_mock.assert_not_awaited()
    assert result == {
        "team_id": 42,
        "team_disabled": False,
        "workflows_started": 0,
        "workflows_skipped_already_running": 0,
        "dry_run": False,
    }


@pytest.mark.asyncio
async def test_workflow_dry_run_skips_child_start():
    @activity.defn(name="find_sessions_for_team_activity")
    async def find_sessions_mocked(inputs: FindSessionsInput) -> FindSessionsResult:
        return FindSessionsResult(team_id=inputs.team_id, session_ids=["s1", "s2"], user_id=7)

    @activity.defn(name="delete_team_schedule_activity")
    async def delete_schedule_mocked(inputs: DeleteTeamScheduleInput) -> None:
        pass

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SummarizeTeamSessionsWorkflow],
            activities=[find_sessions_mocked, delete_schedule_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                SummarizeTeamSessionsInputs(team_id=42, dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result == {
        "team_id": 42,
        "team_disabled": False,
        "workflows_started": 0,
        "workflows_skipped_already_running": 0,
        "dry_run": True,
    }


@pytest.mark.asyncio
async def test_workflow_dry_run_propagates_to_delete_activity():
    delete_inputs: list[DeleteTeamScheduleInput] = []

    @activity.defn(name="find_sessions_for_team_activity")
    async def find_sessions_mocked(inputs: FindSessionsInput) -> FindSessionsResult:
        return FindSessionsResult(team_id=inputs.team_id, team_disabled=True)

    @activity.defn(name="delete_team_schedule_activity")
    async def delete_schedule_mocked(inputs: DeleteTeamScheduleInput) -> None:
        delete_inputs.append(inputs)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SummarizeTeamSessionsWorkflow],
            activities=[find_sessions_mocked, delete_schedule_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                SummarizeTeamSessionsInputs(team_id=42, dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert delete_inputs == [DeleteTeamScheduleInput(team_id=42, dry_run=True)]
    assert result["dry_run"] is True
