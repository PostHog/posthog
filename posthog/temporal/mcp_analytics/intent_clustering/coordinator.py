"""Coordinator workflow for daily MCP analytics intent clustering.

Discovers teams via ``get_team_ids_for_mcp_analytics`` and fans out one
``DailyIntentClusteringWorkflow`` per team. Per-team failures are isolated
so one slow or broken team can't block the rest.

Uses ``continue_as_new`` when Temporal suggests it so the workflow history
stays under the 50k event cap when discovery grows.
"""

import dataclasses
from typing import Any

import structlog
import temporalio
from temporalio.workflow import ChildWorkflowHandle

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.mcp_analytics.intent_clustering.constants import (
    CHILD_WORKFLOW_ID_PREFIX,
    COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
    COORDINATOR_DEFAULT_MAX_CONCURRENT_TEAMS,
    COORDINATOR_WORKFLOW_NAME,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_TOP_N_INTENTS,
    WORKFLOW_EXECUTION_TIMEOUT,
)
from posthog.temporal.mcp_analytics.intent_clustering.models import (
    IntentClusteringResult,
    IntentClusteringWorkflowInputs,
)
from posthog.temporal.mcp_analytics.intent_clustering.workflow import DailyIntentClusteringWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.mcp_analytics.intent_clustering.team_discovery import (
        DISCOVERY_ACTIVITY_RETRY_POLICY,
        DISCOVERY_ACTIVITY_TIMEOUT,
        GUARANTEED_TEAM_IDS,
        TeamDiscoveryInput,
        get_team_ids_for_mcp_analytics,
    )

logger = structlog.get_logger(__name__)


def _empty_results() -> dict[str, Any]:
    return {
        "teams_succeeded": 0,
        "teams_failed": 0,
        "failed_team_ids": [],
        "total_intents": 0,
        "total_clusters": 0,
    }


@dataclasses.dataclass
class IntentClusteringCoordinatorInputs:
    """Inputs for the coordinator workflow.

    ``remaining_team_ids`` and ``results_so_far`` are only set on the
    continue-as-new leg — they carry partial progress across continuations
    so team discovery isn't re-run.
    """

    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    top_n: int = DEFAULT_TOP_N_INTENTS
    max_concurrent_teams: int = COORDINATOR_DEFAULT_MAX_CONCURRENT_TEAMS
    remaining_team_ids: list[int] | None = None
    results_so_far: dict[str, Any] | None = None


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class IntentClusteringCoordinatorWorkflow(PostHogWorkflow):
    """Fan-out coordinator. Spawns one DailyIntentClusteringWorkflow per team."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IntentClusteringCoordinatorInputs:
        return IntentClusteringCoordinatorInputs(
            lookback_days=int(inputs[0]) if len(inputs) > 0 else DEFAULT_LOOKBACK_DAYS,
            top_n=int(inputs[1]) if len(inputs) > 1 else DEFAULT_TOP_N_INTENTS,
            max_concurrent_teams=(int(inputs[2]) if len(inputs) > 2 else COORDINATOR_DEFAULT_MAX_CONCURRENT_TEAMS),
        )

    @temporalio.workflow.run
    async def run(self, inputs: IntentClusteringCoordinatorInputs) -> dict[str, Any]:
        # Phase A: resolve teams. Skip discovery on continuation legs.
        if inputs.remaining_team_ids is not None:
            team_ids = inputs.remaining_team_ids
            results_so_far = inputs.results_so_far or _empty_results()
            logger.info(
                "mcpa.intent_clustering.coordinator.resumed",
                remaining_teams=len(team_ids),
                teams_succeeded_so_far=results_so_far["teams_succeeded"],
            )
        else:
            logger.info(
                "mcpa.intent_clustering.coordinator.started",
                lookback_days=inputs.lookback_days,
                top_n=inputs.top_n,
            )
            try:
                team_ids = await temporalio.workflow.execute_activity(
                    get_team_ids_for_mcp_analytics,
                    TeamDiscoveryInput(),
                    start_to_close_timeout=DISCOVERY_ACTIVITY_TIMEOUT,
                    retry_policy=DISCOVERY_ACTIVITY_RETRY_POLICY,
                )
            except Exception:
                logger.warning(
                    "mcpa.intent_clustering.coordinator.discovery_failed_using_fallback",
                    exc_info=True,
                )
                team_ids = sorted(GUARANTEED_TEAM_IDS)

            results_so_far = _empty_results()
            logger.info(
                "mcpa.intent_clustering.coordinator.teams_resolved",
                team_count=len(team_ids),
                team_ids=team_ids,
            )

        # Phase B: process teams in batches.
        max_concurrent = inputs.max_concurrent_teams
        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]
            handles: list[tuple[int, ChildWorkflowHandle[DailyIntentClusteringWorkflow, IntentClusteringResult]]] = []
            for team_id in batch:
                handle = await temporalio.workflow.start_child_workflow(
                    DailyIntentClusteringWorkflow.run,
                    IntentClusteringWorkflowInputs(
                        team_id=team_id, lookback_days=inputs.lookback_days, top_n=inputs.top_n
                    ),
                    id=(f"{CHILD_WORKFLOW_ID_PREFIX}-{team_id}-{temporalio.workflow.now().isoformat()}"),
                    execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
                    retry_policy=COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.TERMINATE,
                )
                handles.append((team_id, handle))

            for team_id, handle in handles:
                try:
                    child_result: IntentClusteringResult = await handle
                    results_so_far["total_intents"] += child_result.n_intents
                    results_so_far["total_clusters"] += child_result.n_clusters
                    results_so_far["teams_succeeded"] += 1
                    logger.info(
                        "mcpa.intent_clustering.coordinator.team_completed",
                        team_id=team_id,
                        n_intents=child_result.n_intents,
                        n_clusters=child_result.n_clusters,
                    )
                except Exception:
                    logger.exception("mcpa.intent_clustering.coordinator.team_failed", team_id=team_id)
                    results_so_far["failed_team_ids"].append(team_id)
                    results_so_far["teams_failed"] += 1

            # If Temporal suggests continue-as-new and we have more teams, carry state forward.
            remaining = team_ids[batch_start + max_concurrent :]
            if remaining and temporalio.workflow.info().is_continue_as_new_suggested():
                logger.info(
                    "mcpa.intent_clustering.coordinator.continuing_as_new",
                    teams_remaining=len(remaining),
                )
                temporalio.workflow.continue_as_new(
                    IntentClusteringCoordinatorInputs(
                        lookback_days=inputs.lookback_days,
                        top_n=inputs.top_n,
                        max_concurrent_teams=inputs.max_concurrent_teams,
                        remaining_team_ids=remaining,
                        results_so_far=results_so_far,
                    )
                )

        total = results_so_far["teams_succeeded"] + results_so_far["teams_failed"]
        logger.info(
            "mcpa.intent_clustering.coordinator.finished",
            teams_processed=total,
            teams_succeeded=results_so_far["teams_succeeded"],
            teams_failed=results_so_far["teams_failed"],
            total_intents=results_so_far["total_intents"],
            total_clusters=results_so_far["total_clusters"],
        )

        return {
            "teams_processed": total,
            "teams_succeeded": results_so_far["teams_succeeded"],
            "teams_failed": results_so_far["teams_failed"],
            "failed_team_ids": results_so_far["failed_team_ids"],
            "total_intents": results_so_far["total_intents"],
            "total_clusters": results_so_far["total_clusters"],
        }
