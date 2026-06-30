"""Tests for the DailyIntentClusteringWorkflow envelope.

The pure pipeline (corpus fetch, embedding cache, clustering, snapshot
shape) is covered in ``products/mcp_analytics/backend/tests/``. These
tests assert the workflow forwards inputs to the activity and returns its
result — the wiring, not the algorithm.
"""

import uuid

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.mcp_analytics.intent_clustering.models import (
    IntentClusteringResult,
    IntentClusteringWorkflowInputs,
)
from posthog.temporal.mcp_analytics.intent_clustering.workflow import DailyIntentClusteringWorkflow


async def _run_with_mock_activity(
    inputs: IntentClusteringWorkflowInputs,
    activity_result: IntentClusteringResult,
) -> tuple[IntentClusteringResult, IntentClusteringWorkflowInputs]:
    """Execute the workflow in a time-skipping environment with a stub activity.

    Returns ``(workflow_result, activity_inputs_seen)`` so callers can assert
    both ends of the contract.
    """
    captured: dict[str, IntentClusteringWorkflowInputs] = {}

    @activity.defn(name="compute_intent_clusters_activity")
    async def mock_activity(activity_inputs: IntentClusteringWorkflowInputs) -> IntentClusteringResult:
        captured["inputs"] = activity_inputs
        return activity_result

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[DailyIntentClusteringWorkflow],
            activities=[mock_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                DailyIntentClusteringWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    return result, captured["inputs"]


class TestDailyIntentClusteringWorkflow:
    @pytest.mark.asyncio
    async def test_forwards_inputs_to_activity(self) -> None:
        inputs = IntentClusteringWorkflowInputs(team_id=42, lookback_days=14, top_n=200, user_id=7)
        expected = IntentClusteringResult(
            team_id=42, n_intents=10, n_clusters=2, computed_at="2026-05-21T00:00:00+00:00"
        )

        result, activity_inputs = await _run_with_mock_activity(inputs, expected)

        assert activity_inputs.team_id == 42
        assert activity_inputs.lookback_days == 14
        assert activity_inputs.top_n == 200
        assert activity_inputs.user_id == 7
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_activity_result_unchanged(self) -> None:
        inputs = IntentClusteringWorkflowInputs(team_id=1)
        expected = IntentClusteringResult(team_id=1, n_intents=0, n_clusters=0, computed_at="2026-05-21T00:00:00+00:00")

        result, _ = await _run_with_mock_activity(inputs, expected)

        assert result == expected


class TestParseInputs:
    @pytest.mark.parametrize(
        "raw_payload, expected_team_id, expected_lookback_days, expected_top_n, expected_user_id",
        [
            # Empty input falls back to dataclass defaults.
            ([], 0, 7, 500, None),
            # Full JSON payload overrides every field.
            (['{"team_id": 99, "lookback_days": 3, "top_n": 50, "user_id": 5}'], 99, 3, 50, 5),
            # Partial payload preserves dataclass defaults for omitted fields.
            (['{"team_id": 99}'], 99, 7, 500, None),
        ],
    )
    def test_parse_inputs_cases(
        self,
        raw_payload: list[str],
        expected_team_id: int,
        expected_lookback_days: int,
        expected_top_n: int,
        expected_user_id: int | None,
    ) -> None:
        inputs = DailyIntentClusteringWorkflow.parse_inputs(raw_payload)
        assert inputs.team_id == expected_team_id
        assert inputs.lookback_days == expected_lookback_days
        assert inputs.top_n == expected_top_n
        assert inputs.user_id == expected_user_id
