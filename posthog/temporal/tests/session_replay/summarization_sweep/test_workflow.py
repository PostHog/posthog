import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.summarization_sweep.constants import WORKFLOW_NAME
from posthog.temporal.session_replay.summarization_sweep.types import (
    ConsumeSummaryQuotaInput,
    FindSessionsInput,
    FindSessionsResult,
    SummarizeTeamSessionsInputs,
)
from posthog.temporal.session_replay.summarization_sweep.workflow import SummarizeTeamSessionsWorkflow


@pytest.mark.asyncio
async def test_workflow_noop_when_no_sessions():
    @activity.defn(name="find_sessions_for_team_activity")
    async def find_sessions_mocked(inputs: FindSessionsInput) -> FindSessionsResult:
        return FindSessionsResult(team_id=inputs.team_id, session_ids=[], user_id=None)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SummarizeTeamSessionsWorkflow],
            activities=[find_sessions_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                SummarizeTeamSessionsInputs(team_id=42),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result == {
        "team_id": 42,
        "workflows_started": 0,
        "workflows_skipped_already_running": 0,
    }


async def _fake_start_child(
    self: SummarizeTeamSessionsWorkflow,
    team_id: int,
    session_id: str,
    user_id: int,
    user_distinct_id: str | None,
) -> bool:
    """Replacement for `_start_child` in tests so we don't have to register a
    real child workflow + worker. With ABANDON parent-close + time skipping,
    pending children keep the test env alive until their execution_timeout
    (~45 minutes), which deadlocks the test."""
    return True


@pytest.mark.asyncio
async def test_workflow_consumes_quota_after_dispatching_children(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(SummarizeTeamSessionsWorkflow, "_start_child", _fake_start_child)

    @activity.defn(name="find_sessions_for_team_activity")
    async def find_sessions_mocked(inputs: FindSessionsInput) -> FindSessionsResult:
        return FindSessionsResult(
            team_id=inputs.team_id,
            session_ids=["s1"],
            user_id=7,
            user_distinct_id="distinct",
        )

    consume_calls: list[ConsumeSummaryQuotaInput] = []

    @activity.defn(name="consume_summary_quota_activity")
    async def consume_mocked(inputs: ConsumeSummaryQuotaInput) -> None:
        consume_calls.append(inputs)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SummarizeTeamSessionsWorkflow],
            activities=[find_sessions_mocked, consume_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                SummarizeTeamSessionsInputs(team_id=42),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result["workflows_started"] == 1
    assert len(consume_calls) == 1
    assert consume_calls[0].team_id == 42
    assert consume_calls[0].n == 1


@pytest.mark.asyncio
async def test_workflow_does_not_fail_when_consume_quota_activity_fails(monkeypatch: pytest.MonkeyPatch):
    """A transient Redis blip in the bookkeeping activity must not roll up as
    a workflow failure — the children were dispatched successfully, and the
    next sweep tick refills the increment naturally."""
    monkeypatch.setattr(SummarizeTeamSessionsWorkflow, "_start_child", _fake_start_child)

    @activity.defn(name="find_sessions_for_team_activity")
    async def find_sessions_mocked(inputs: FindSessionsInput) -> FindSessionsResult:
        return FindSessionsResult(
            team_id=inputs.team_id,
            session_ids=["s1"],
            user_id=7,
            user_distinct_id="distinct",
        )

    @activity.defn(name="consume_summary_quota_activity")
    async def consume_failing(inputs: ConsumeSummaryQuotaInput) -> None:
        raise RuntimeError("redis is on fire")

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SummarizeTeamSessionsWorkflow],
            activities=[find_sessions_mocked, consume_failing],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                SummarizeTeamSessionsInputs(team_id=42),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result == {
        "team_id": 42,
        "workflows_started": 1,
        "workflows_skipped_already_running": 0,
    }
