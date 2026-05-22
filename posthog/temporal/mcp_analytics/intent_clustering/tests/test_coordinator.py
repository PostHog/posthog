"""Tests for the IntentClusteringCoordinatorWorkflow."""

import uuid
from typing import Any

import pytest

from temporalio import activity, workflow
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.mcp_analytics.intent_clustering.coordinator import (
    IntentClusteringCoordinatorInputs,
    IntentClusteringCoordinatorWorkflow,
)
from posthog.temporal.mcp_analytics.intent_clustering.models import (
    IntentClusteringResult,
    IntentClusteringWorkflowInputs,
)
from posthog.temporal.mcp_analytics.intent_clustering.team_discovery import GUARANTEED_TEAM_IDS, TeamDiscoveryInput

# Module-level mock child workflow. Temporal sandbox forbids local-class
# @workflow.defn, and per-test workflow classes with the same name collide
# anyway — share one class and toggle behaviour via a module-level set the
# test populates before running.
_FAILING_TEAM_IDS: set[int] = set()


@workflow.defn(name="mcpa-intent-clustering")
class StubDailyWorkflow:
    @workflow.run
    async def run(self, inputs: IntentClusteringWorkflowInputs) -> IntentClusteringResult:
        if inputs.team_id in _FAILING_TEAM_IDS:
            # ApplicationError fails the *execution*, not the workflow task —
            # a plain RuntimeError makes Temporal retry the task indefinitely
            # against the execution timeout, which hangs time-skipping tests.
            raise ApplicationError(f"team {inputs.team_id} blew up", non_retryable=True)
        # n_intents is tied to team_id so each child's contribution is
        # identifiable in aggregate-result assertions.
        return IntentClusteringResult(
            team_id=inputs.team_id,
            n_intents=inputs.team_id * 10,
            n_clusters=inputs.team_id,
            computed_at="2026-05-21T00:00:00+00:00",
        )


async def _run_coordinator(
    team_ids: list[int],
    coordinator_inputs: IntentClusteringCoordinatorInputs,
    *,
    failing_team_id: int | None = None,
) -> dict[str, Any]:
    """Drive the coordinator with mocked discovery + child workflow."""

    @activity.defn(name="get_team_ids_for_mcp_analytics")
    async def mock_discovery(_: TeamDiscoveryInput) -> list[int]:
        return team_ids

    _FAILING_TEAM_IDS.clear()
    if failing_team_id is not None:
        _FAILING_TEAM_IDS.add(failing_team_id)

    task_queue = str(uuid.uuid4())
    try:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[IntentClusteringCoordinatorWorkflow, StubDailyWorkflow],
                activities=[mock_discovery],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                return await env.client.execute_workflow(
                    IntentClusteringCoordinatorWorkflow.run,
                    coordinator_inputs,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
    finally:
        _FAILING_TEAM_IDS.clear()


class TestIntentClusteringCoordinator:
    @pytest.mark.asyncio
    async def test_runs_one_child_per_discovered_team(self) -> None:
        result = await _run_coordinator(
            team_ids=[2, 7, 9],
            coordinator_inputs=IntentClusteringCoordinatorInputs(),
        )
        assert result["teams_processed"] == 3
        assert result["teams_succeeded"] == 3
        assert result["teams_failed"] == 0
        assert result["failed_team_ids"] == []
        assert result["total_intents"] == 20 + 70 + 90
        assert result["total_clusters"] == 2 + 7 + 9

    @pytest.mark.asyncio
    async def test_per_team_failure_does_not_block_others(self) -> None:
        result = await _run_coordinator(
            team_ids=[2, 7],
            coordinator_inputs=IntentClusteringCoordinatorInputs(),
            failing_team_id=7,
        )
        assert result["teams_succeeded"] == 1
        assert result["teams_failed"] == 1
        assert result["failed_team_ids"] == [7]
        # Only the successful team's intents counted.
        assert result["total_intents"] == 20
        assert result["total_clusters"] == 2

    @pytest.mark.asyncio
    async def test_no_teams_yields_zero_results(self) -> None:
        result = await _run_coordinator(
            team_ids=[],
            coordinator_inputs=IntentClusteringCoordinatorInputs(),
        )
        assert result["teams_processed"] == 0
        assert result["teams_succeeded"] == 0
        assert result["teams_failed"] == 0
        assert result["total_intents"] == 0


class TestCoordinatorParseInputs:
    def test_empty_args_uses_defaults(self) -> None:
        inputs = IntentClusteringCoordinatorWorkflow.parse_inputs([])
        assert inputs.lookback_days == 7
        assert inputs.top_n == 500
        assert inputs.max_concurrent_teams == 4

    def test_parses_positional_args(self) -> None:
        inputs = IntentClusteringCoordinatorWorkflow.parse_inputs(["14", "200", "2"])
        assert inputs.lookback_days == 14
        assert inputs.top_n == 200
        assert inputs.max_concurrent_teams == 2


class TestGuaranteedTeamIds:
    def test_includes_internal_team(self) -> None:
        # If this changes, double-check the coordinator schedule isn't sending
        # daily traffic to an unexpected team.
        assert 2 in GUARANTEED_TEAM_IDS
