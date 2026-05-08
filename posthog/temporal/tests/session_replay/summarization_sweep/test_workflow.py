import uuid

import pytest

import temporalio.worker
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.session_summary.types.inputs import SingleSessionSummaryInputs
from posthog.temporal.session_replay.summarization_sweep.constants import WORKFLOW_NAME
from posthog.temporal.session_replay.summarization_sweep.types import (
    ConsumeSummaryQuotaInput,
    FindSessionsInput,
    FindSessionsResult,
    SummarizeTeamSessionsInputs,
)
from posthog.temporal.session_replay.summarization_sweep.workflow import SummarizeTeamSessionsWorkflow


@workflow.defn(name="summarize-session")
class _NoopChildWorkflow:
    """Stand-in for the real summarize-session child so the sweep workflow has
    something to dispatch into. ABANDON parent close policy means the parent
    doesn't await this; we don't care what it does past being startable."""

    @workflow.run
    async def run(self, inputs: SingleSessionSummaryInputs) -> None:
        return None


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


@pytest.mark.asyncio
async def test_workflow_consumes_quota_after_dispatching_children():
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
            workflows=[SummarizeTeamSessionsWorkflow, _NoopChildWorkflow],
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
async def test_workflow_does_not_fail_when_consume_quota_activity_fails():
    """A transient Redis blip in the bookkeeping activity must not roll up as
    a workflow failure — the children were dispatched successfully, and the
    next sweep tick refills the increment naturally."""

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
            workflows=[SummarizeTeamSessionsWorkflow, _NoopChildWorkflow],
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
