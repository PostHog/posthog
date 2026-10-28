"""Fan-out coordinator: one ``IntentTopicsWorkflow`` of the given kind per discovered team."""

import dataclasses
from typing import Any

import structlog
import temporalio
from temporalio.workflow import ChildWorkflowHandle

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.mcp_analytics.intent_topics.constants import (
    CHILD_WORKFLOW_ID_PREFIX,
    COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
    COORDINATOR_DEFAULT_MAX_CONCURRENT_TEAMS,
    COORDINATOR_WORKFLOW_NAME,
    WORKFLOW_EXECUTION_TIMEOUTS,
)
from posthog.temporal.mcp_analytics.intent_topics.models import IntentTopicsWorkflowInputs, IntentTopicsWorkflowResult
from posthog.temporal.mcp_analytics.intent_topics.workflow import IntentTopicsWorkflow

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
    return {"teams_succeeded": 0, "teams_failed": 0, "teams_skipped": 0, "failed_team_ids": []}


@dataclasses.dataclass(frozen=True)
class IntentTopicsCoordinatorInputs:
    kind: str = "sync"
    max_concurrent_teams: int = COORDINATOR_DEFAULT_MAX_CONCURRENT_TEAMS
    remaining_team_ids: list[int] | None = None
    results_so_far: dict[str, Any] | None = None


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class IntentTopicsCoordinatorWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> IntentTopicsCoordinatorInputs:
        return IntentTopicsCoordinatorInputs(
            kind=inputs[0] if inputs else "sync",
            max_concurrent_teams=int(inputs[1]) if len(inputs) > 1 else COORDINATOR_DEFAULT_MAX_CONCURRENT_TEAMS,
        )

    @temporalio.workflow.run
    async def run(self, inputs: IntentTopicsCoordinatorInputs) -> dict[str, Any]:
        if inputs.remaining_team_ids is not None:
            team_ids = inputs.remaining_team_ids
            results = inputs.results_so_far or _empty_results()
        else:
            try:
                team_ids = await temporalio.workflow.execute_activity(
                    get_team_ids_for_mcp_analytics,
                    TeamDiscoveryInput(),
                    start_to_close_timeout=DISCOVERY_ACTIVITY_TIMEOUT,
                    retry_policy=DISCOVERY_ACTIVITY_RETRY_POLICY,
                )
            except Exception:
                logger.warning("mcpa.intent_topics.coordinator.discovery_failed_using_fallback", exc_info=True)
                team_ids = sorted(GUARANTEED_TEAM_IDS)
            results = _empty_results()
            logger.info("mcpa.intent_topics.coordinator.started", kind=inputs.kind, team_ids=team_ids)

        max_concurrent = inputs.max_concurrent_teams
        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]
            handles: list[tuple[int, ChildWorkflowHandle[IntentTopicsWorkflow, IntentTopicsWorkflowResult]]] = []
            for team_id in batch:
                handle = await temporalio.workflow.start_child_workflow(
                    IntentTopicsWorkflow.run,
                    IntentTopicsWorkflowInputs(team_id=team_id, kind=inputs.kind),
                    id=f"{CHILD_WORKFLOW_ID_PREFIX}-{team_id}-{inputs.kind}-{temporalio.workflow.now().isoformat()}",
                    execution_timeout=WORKFLOW_EXECUTION_TIMEOUTS.get(
                        inputs.kind, WORKFLOW_EXECUTION_TIMEOUTS["refit"]
                    ),
                    retry_policy=COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.TERMINATE,
                )
                handles.append((team_id, handle))
            for team_id, handle in handles:
                try:
                    child: IntentTopicsWorkflowResult = await handle
                    if child.status == "succeeded":
                        results["teams_succeeded"] += 1
                    else:
                        results["teams_skipped"] += 1
                    logger.info("mcpa.intent_topics.coordinator.team_completed", team_id=team_id, status=child.status)
                except Exception:
                    logger.exception("mcpa.intent_topics.coordinator.team_failed", team_id=team_id)
                    results["failed_team_ids"].append(team_id)
                    results["teams_failed"] += 1

            remaining = team_ids[batch_start + max_concurrent :]
            if remaining and temporalio.workflow.info().is_continue_as_new_suggested():
                temporalio.workflow.continue_as_new(
                    IntentTopicsCoordinatorInputs(
                        kind=inputs.kind,
                        max_concurrent_teams=inputs.max_concurrent_teams,
                        remaining_team_ids=remaining,
                        results_so_far=results,
                    )
                )
        return results
