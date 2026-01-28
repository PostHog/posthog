"""
Coordinator workflow for daily trace clustering.

This workflow processes traces for teams in the ALLOWED_TEAM_IDS list
and spawns child workflows to cluster traces for each team.

Team discovery uses a simple allowlist approach to avoid cross-team
ClickHouse queries. The per-team child workflows handle the case where
a team has no traces gracefully (returning empty results).
"""

import dataclasses
from typing import Any

import structlog
import temporalio
from temporalio.workflow import ChildWorkflowHandle

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.constants import (
    ALLOWED_TEAM_IDS,
    CHILD_WORKFLOW_ID_PREFIX,
    COORDINATOR_WORKFLOW_NAME,
)
from posthog.temporal.llm_analytics.trace_clustering.models import (
    AnalysisLevel,
    ClusteringResult,
    ClusteringWorkflowInputs,
)
from posthog.temporal.llm_analytics.trace_clustering.workflow import DailyTraceClusteringWorkflow

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class TraceClusteringCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    analysis_level: AnalysisLevel = "trace"  # "trace" or "generation"
    lookback_days: int = constants.DEFAULT_LOOKBACK_DAYS
    max_samples: int = constants.DEFAULT_MAX_SAMPLES
    min_k: int = constants.DEFAULT_MIN_K
    max_k: int = constants.DEFAULT_MAX_K
    max_concurrent_teams: int = constants.DEFAULT_MAX_CONCURRENT_TEAMS


def get_allowed_team_ids() -> list[int]:
    """
    Get the list of team IDs that should be processed for trace clustering.

    Uses a simple allowlist approach to avoid cross-team ClickHouse queries.
    Per-team child workflows handle the case where a team has no traces gracefully.

    Returns:
        List of team IDs from ALLOWED_TEAM_IDS constant
    """
    return ALLOWED_TEAM_IDS.copy()


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class TraceClusteringCoordinatorWorkflow(PostHogWorkflow):
    """
    Coordinator workflow that processes traces for teams in ALLOWED_TEAM_IDS.

    This runs on a schedule (e.g., daily) and spawns child workflows for each
    team in the allowlist. Teams with no traces will complete quickly with
    empty results.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TraceClusteringCoordinatorInputs:
        """Parse workflow inputs from string list."""
        return TraceClusteringCoordinatorInputs(
            analysis_level="generation" if len(inputs) > 0 and inputs[0] == "generation" else "trace",
            lookback_days=int(inputs[1]) if len(inputs) > 1 else constants.DEFAULT_LOOKBACK_DAYS,
            max_samples=int(inputs[2]) if len(inputs) > 2 else constants.DEFAULT_MAX_SAMPLES,
            min_k=int(inputs[3]) if len(inputs) > 3 else constants.DEFAULT_MIN_K,
            max_k=int(inputs[4]) if len(inputs) > 4 else constants.DEFAULT_MAX_K,
            max_concurrent_teams=int(inputs[5]) if len(inputs) > 5 else constants.DEFAULT_MAX_CONCURRENT_TEAMS,
        )

    @temporalio.workflow.run
    async def run(self, inputs: TraceClusteringCoordinatorInputs) -> dict[str, Any]:
        """Execute coordinator workflow."""
        logger.info(
            "Starting trace clustering coordinator",
            analysis_level=inputs.analysis_level,
            lookback_days=inputs.lookback_days,
            max_samples=inputs.max_samples,
        )

        # Get teams from allowlist (no cross-team ClickHouse query needed)
        team_ids = get_allowed_team_ids()

        if not team_ids:
            logger.info("No teams in allowlist")
            return {
                "teams_processed": 0,
                "total_clusters": 0,
            }

        logger.info("Processing teams from allowlist", team_count=len(team_ids), team_ids=team_ids)

        # Spawn child workflows for each team with concurrency limit
        total_clusters = 0
        total_items = 0
        failed_teams: list[int] = []
        successful_teams: list[int] = []

        # Process teams in batches for controlled parallelism
        max_concurrent = inputs.max_concurrent_teams

        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]

            # Start all workflows in batch concurrently
            workflow_handles: list[tuple[int, ChildWorkflowHandle[DailyTraceClusteringWorkflow, ClusteringResult]]] = []
            for team_id in batch:
                handle = await temporalio.workflow.start_child_workflow(
                    DailyTraceClusteringWorkflow.run,
                    ClusteringWorkflowInputs(
                        team_id=team_id,
                        analysis_level=inputs.analysis_level,
                        lookback_days=inputs.lookback_days,
                        max_samples=inputs.max_samples,
                        min_k=inputs.min_k,
                        max_k=inputs.max_k,
                    ),
                    id=f"{CHILD_WORKFLOW_ID_PREFIX}-{team_id}-{temporalio.workflow.now().isoformat()}",
                    execution_timeout=constants.WORKFLOW_EXECUTION_TIMEOUT,
                    retry_policy=constants.COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )
                workflow_handles.append((team_id, handle))

            # Wait for all workflows in batch to complete
            for team_id, handle in workflow_handles:
                try:
                    workflow_result: ClusteringResult = await handle
                    total_clusters += workflow_result.metrics.num_clusters
                    total_items += workflow_result.metrics.total_items_analyzed
                    successful_teams.append(team_id)

                    logger.info(
                        "Completed clustering for team",
                        team_id=team_id,
                        items=workflow_result.metrics.total_items_analyzed,
                        clusters=workflow_result.metrics.num_clusters,
                    )

                except Exception:
                    logger.exception("Failed to cluster team", team_id=team_id)
                    failed_teams.append(team_id)

        logger.info(
            "Trace clustering coordinator completed",
            teams_processed=len(team_ids),
            teams_succeeded=len(successful_teams),
            teams_failed=len(failed_teams),
            total_items=total_items,
            total_clusters=total_clusters,
        )

        return {
            "teams_processed": len(team_ids),
            "teams_succeeded": len(successful_teams),
            "teams_failed": len(failed_teams),
            "failed_team_ids": failed_teams,
            "total_items": total_items,
            "total_clusters": total_clusters,
        }
