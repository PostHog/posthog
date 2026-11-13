"""Wiring tests for ``IntentTopicsWorkflow``: which activities run for which kind."""

import uuid
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.mcp_analytics.intent_topics.constants import (
    ACTIVITY_RETRY_POLICY,
    ASSIGN_ACTIVITY_TIMEOUT,
    REFIT_ACTIVITY_TIMEOUT,
    SYNC_ACTIVITY_TIMEOUT,
    WORKFLOW_EXECUTION_TIMEOUTS,
)
from posthog.temporal.mcp_analytics.intent_topics.models import IntentTopicsRunResult, IntentTopicsWorkflowInputs
from posthog.temporal.mcp_analytics.intent_topics.workflow import IntentTopicsWorkflow


async def _run(
    inputs: IntentTopicsWorkflowInputs, refit_status: str = "succeeded"
) -> tuple[list[str], list[IntentTopicsRunResult]]:
    calls: list[str] = []

    def _stub(name: str, status: str = "succeeded"):
        @activity.defn(name=name)
        async def stub(activity_inputs: IntentTopicsWorkflowInputs) -> IntentTopicsRunResult:
            calls.append(name)
            return IntentTopicsRunResult(
                team_id=activity_inputs.team_id, kind=activity_inputs.kind, status=status, run_id=name
            )

        return stub

    activities = [
        _stub("sync_intent_embeddings_activity"),
        _stub("assign_intent_topics_activity"),
        _stub("refit_intent_topics_activity", refit_status),
        _stub("reassign_after_refit_activity"),
    ]
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[IntentTopicsWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                IntentTopicsWorkflow.run, inputs, id=str(uuid.uuid4()), task_queue=task_queue
            )
    return calls, result.runs


class TestIntentTopicsWorkflow:
    @pytest.mark.asyncio
    async def test_sync_runs_only_the_sync_activity(self) -> None:
        calls, runs = await _run(IntentTopicsWorkflowInputs(team_id=2, kind="sync"))

        assert calls == ["sync_intent_embeddings_activity"]
        assert [r.kind for r in runs] == ["sync"]

    @pytest.mark.asyncio
    async def test_assign_runs_only_the_assign_activity(self) -> None:
        calls, _ = await _run(IntentTopicsWorkflowInputs(team_id=2, kind="assign"))

        assert calls == ["assign_intent_topics_activity"]

    @pytest.mark.asyncio
    async def test_refit_then_reassigns_the_window(self) -> None:
        calls, runs = await _run(IntentTopicsWorkflowInputs(team_id=2, kind="refit", now="2026-10-20T02:00:00+00:00"))

        assert calls == ["refit_intent_topics_activity", "reassign_after_refit_activity"]
        assert len(runs) == 2

    @pytest.mark.asyncio
    async def test_skipped_refit_does_not_reassign(self) -> None:
        calls, _ = await _run(IntentTopicsWorkflowInputs(team_id=2, kind="refit"), refit_status="skipped_too_few")

        assert calls == ["refit_intent_topics_activity"]

    @pytest.mark.asyncio
    async def test_unknown_kind_fails(self) -> None:
        with pytest.raises(WorkflowFailureError) as excinfo:
            await _run(IntentTopicsWorkflowInputs(team_id=2, kind="nope"))
        assert "Unknown run kind" in str(excinfo.value.cause)


class TestParseInputs:
    def test_json_payload(self) -> None:
        inputs = IntentTopicsWorkflow.parse_inputs(['{"team_id": 9, "kind": "refit"}'])
        assert (inputs.team_id, inputs.kind, inputs.now) == (9, "refit", "")

    def test_empty_payload_defaults(self) -> None:
        inputs = IntentTopicsWorkflow.parse_inputs([])
        assert (inputs.team_id, inputs.kind) == (0, "sync")


@pytest.mark.parametrize(
    "kind, activity_timeouts",
    [
        ("sync", [SYNC_ACTIVITY_TIMEOUT]),
        ("assign", [ASSIGN_ACTIVITY_TIMEOUT]),
        ("refit", [REFIT_ACTIVITY_TIMEOUT, ASSIGN_ACTIVITY_TIMEOUT]),
    ],
)
def test_workflow_timeout_outlasts_every_activity_attempt(kind: str, activity_timeouts: list[timedelta]) -> None:
    attempts = ACTIVITY_RETRY_POLICY.maximum_attempts or 1
    assert WORKFLOW_EXECUTION_TIMEOUTS[kind] > sum((timeout * attempts for timeout in activity_timeouts), timedelta())
