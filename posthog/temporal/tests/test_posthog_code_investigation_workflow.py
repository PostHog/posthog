from __future__ import annotations

import uuid

import pytest

from django.conf import settings

import temporalio.activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.alerts.posthog_code_investigation import (
    CreateInvestigationTaskResult,
    InvestigationRunState,
    PostHogCodeInvestigationInputs,
    PostHogCodeInvestigationWorkflow,
)

pytestmark = [pytest.mark.asyncio]


def _inputs() -> PostHogCodeInvestigationInputs:
    return PostHogCodeInvestigationInputs(
        team_id=1,
        alert_id=str(uuid.uuid4()),
        alert_check_id=str(uuid.uuid4()),
    )


async def _run(*, terminal_on_poll: int | None, create_status: str = "created") -> dict[str, int]:
    """Run the workflow with stub activities; return per-activity call counts.

    terminal_on_poll: which poll (1-indexed) returns terminal; None = never terminal.
    """
    calls = {"create": 0, "poll": 0, "finalize": 0, "cancel": 0}

    @temporalio.activity.defn(name="create_posthog_code_investigation_task")
    async def create(inputs: PostHogCodeInvestigationInputs) -> CreateInvestigationTaskResult:
        calls["create"] += 1
        return CreateInvestigationTaskResult(status=create_status, task_run_id="run-1")

    @temporalio.activity.defn(name="get_investigation_run_state")
    async def poll(inputs: PostHogCodeInvestigationInputs) -> InvestigationRunState:
        calls["poll"] += 1
        terminal = terminal_on_poll is not None and calls["poll"] >= terminal_on_poll
        return InvestigationRunState(terminal=terminal, status="completed" if terminal else "running")

    @temporalio.activity.defn(name="finalize_posthog_code_investigation")
    async def finalize(inputs: PostHogCodeInvestigationInputs) -> None:
        calls["finalize"] += 1

    @temporalio.activity.defn(name="cancel_posthog_code_investigation")
    async def cancel(inputs: PostHogCodeInvestigationInputs) -> None:
        calls["cancel"] += 1

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            workflows=[PostHogCodeInvestigationWorkflow],
            activities=[create, poll, finalize, cancel],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                PostHogCodeInvestigationWorkflow.run,
                _inputs(),
                id=f"posthog-code-investigation-{uuid.uuid4()}",
                task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            )
    return calls


async def test_exits_without_polling_when_create_not_created() -> None:
    calls = await _run(terminal_on_poll=1, create_status="skipped")
    assert calls == {"create": 1, "poll": 0, "finalize": 0, "cancel": 0}


async def test_finalizes_when_poll_reaches_terminal() -> None:
    calls = await _run(terminal_on_poll=2)
    assert calls["poll"] == 2
    assert calls["finalize"] == 1
    assert calls["cancel"] == 0


async def test_cancels_after_timeout_when_never_terminal() -> None:
    calls = await _run(terminal_on_poll=None)
    assert calls["cancel"] == 1
    assert calls["finalize"] == 0
    assert calls["poll"] >= 1
