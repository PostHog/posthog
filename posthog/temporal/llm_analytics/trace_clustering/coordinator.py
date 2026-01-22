"""
Coordinator workflow for daily trace/generation clustering.

This workflow processes traces or generations for teams in the ALLOWED_TEAM_IDS list
and spawns child workflows to cluster data for each team.

Team discovery uses a simple allowlist approach to avoid cross-team
ClickHouse queries. The per-team child workflows handle the case where
a team has no data gracefully (returning empty results).

Supports both trace-level and generation-level clustering via the analysis_level parameter.
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
    DEFAULT_ANALYSIS_LEVEL,
    ClusteringResult,
    ClusteringWorkflowInputs,
)
from posthog.temporal.llm_analytics.trace_clustering.workflow import DailyTraceClusteringWorkflow

from products.llm_analytics.backend.summarization.models import AnalysisLevel

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class TraceClusteringCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    lookback_days: int = constants.DEFAULT_LOOKBACK_DAYS
    max_samples: int = constants.DEFAULT_MAX_SAMPLES
    min_k: int = constants.DEFAULT_MIN_K
    max_k: int = constants.DEFAULT_MAX_K
    max_concurrent_teams: int = constants.DEFAULT_MAX_CONCURRENT_TEAMS
    analysis_level: AnalysisLevel = dataclasses.field(default=DEFAULT_ANALYSIS_LEVEL)


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
            lookback_days=int(inputs[0]) if len(inputs) > 0 else constants.DEFAULT_LOOKBACK_DAYS,
            max_samples=int(inputs[1]) if len(inputs) > 1 else constants.DEFAULT_MAX_SAMPLES,
            min_k=int(inputs[2]) if len(inputs) > 2 else constants.DEFAULT_MIN_K,
            max_k=int(inputs[3]) if len(inputs) > 3 else constants.DEFAULT_MAX_K,
            max_concurrent_teams=int(inputs[4]) if len(inputs) > 4 else constants.DEFAULT_MAX_CONCURRENT_TEAMS,
            analysis_level=AnalysisLevel(inputs[5]) if len(inputs) > 5 else DEFAULT_ANALYSIS_LEVEL,
        )

    @temporalio.workflow.run
    async def run(self, inputs: TraceClusteringCoordinatorInputs) -> dict[str, Any]:
        """Execute coordinator workflow."""
        level_label = "generation" if inputs.analysis_level == AnalysisLevel.GENERATION else "trace"
        logger.info(
            f"Starting {level_label} clustering coordinator",
            lookback_days=inputs.lookback_days,
            max_samples=inputs.max_samples,
            analysis_level=str(inputs.analysis_level),
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
        total_traces = 0
        failed_teams: list[int] = []
        successful_teams: list[int] = []

        # Process teams in batches for controlled parallelism
        max_concurrent = inputs.max_concurrent_teams

        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]

            # Start all workflows in batch concurrently
            workflow_handles: list[tuple[int, ChildWorkflowHandle[DailyTraceClusteringWorkflow, ClusteringResult]]] = []
            for team_id in batch:
                # Use different ID prefix for generation-level clustering
                id_prefix = (
                    "llma-generation-clustering-team"
                    if inputs.analysis_level == AnalysisLevel.GENERATION
                    else CHILD_WORKFLOW_ID_PREFIX
                )
                handle = await temporalio.workflow.start_child_workflow(
                    DailyTraceClusteringWorkflow.run,
                    ClusteringWorkflowInputs(
                        team_id=team_id,
                        lookback_days=inputs.lookback_days,
                        max_samples=inputs.max_samples,
                        min_k=inputs.min_k,
                        max_k=inputs.max_k,
                        analysis_level=inputs.analysis_level,
                    ),
                    id=f"{id_prefix}-{team_id}-{temporalio.workflow.now().isoformat()}",
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
                    total_traces += workflow_result.metrics.total_traces_analyzed
                    successful_teams.append(team_id)

                    logger.info(
                        "Completed clustering for team",
                        team_id=team_id,
                        traces=workflow_result.metrics.total_traces_analyzed,
                        clusters=workflow_result.metrics.num_clusters,
                    )

                except Exception:
                    logger.exception("Failed to cluster team", team_id=team_id)
                    failed_teams.append(team_id)

        logger.info(
            f"{level_label.capitalize()} clustering coordinator completed",
            teams_processed=len(team_ids),
            teams_succeeded=len(successful_teams),
            teams_failed=len(failed_teams),
            total_traces=total_traces,
            total_clusters=total_clusters,
            analysis_level=str(inputs.analysis_level),
        )

        return {
            "teams_processed": len(team_ids),
            "teams_succeeded": len(successful_teams),
            "teams_failed": len(failed_teams),
            "failed_team_ids": failed_teams,
            "total_traces": total_traces,
            "total_clusters": total_clusters,
            "analysis_level": str(inputs.analysis_level),
        }


@dataclasses.dataclass
class GenerationClusteringCoordinatorInputs:
    """Inputs for the generation-level clustering coordinator workflow.

    This is a convenience wrapper that defaults to GENERATION analysis level.
    """

    lookback_days: int = constants.DEFAULT_LOOKBACK_DAYS
    max_samples: int = constants.DEFAULT_MAX_SAMPLES
    min_k: int = constants.DEFAULT_MIN_K
    max_k: int = constants.DEFAULT_MAX_K
    max_concurrent_teams: int = constants.DEFAULT_MAX_CONCURRENT_TEAMS


@temporalio.workflow.defn(name=constants.GENERATION_COORDINATOR_WORKFLOW_NAME)
class GenerationClusteringCoordinatorWorkflow(PostHogWorkflow):
    """
    Coordinator workflow for generation-level clustering.

    This is a wrapper around TraceClusteringCoordinatorWorkflow that defaults to
    GENERATION analysis level, allowing separate schedules for trace vs generation clustering.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> GenerationClusteringCoordinatorInputs:
        """Parse workflow inputs from string list."""
        return GenerationClusteringCoordinatorInputs(
            lookback_days=int(inputs[0]) if len(inputs) > 0 else constants.DEFAULT_LOOKBACK_DAYS,
            max_samples=int(inputs[1]) if len(inputs) > 1 else constants.DEFAULT_MAX_SAMPLES,
            min_k=int(inputs[2]) if len(inputs) > 2 else constants.DEFAULT_MIN_K,
            max_k=int(inputs[3]) if len(inputs) > 3 else constants.DEFAULT_MAX_K,
            max_concurrent_teams=int(inputs[4]) if len(inputs) > 4 else constants.DEFAULT_MAX_CONCURRENT_TEAMS,
        )

    @temporalio.workflow.run
    async def run(self, inputs: GenerationClusteringCoordinatorInputs) -> dict[str, Any]:
        """Execute generation clustering coordinator by delegating to trace coordinator."""
        # Convert to trace coordinator inputs with GENERATION level
        trace_inputs = TraceClusteringCoordinatorInputs(
            lookback_days=inputs.lookback_days,
            max_samples=inputs.max_samples,
            min_k=inputs.min_k,
            max_k=inputs.max_k,
            max_concurrent_teams=inputs.max_concurrent_teams,
            analysis_level=AnalysisLevel.GENERATION,
        )

        # Execute the trace coordinator workflow logic inline
        # (Can't call another workflow synchronously, so we duplicate the logic)
        level_label = "generation"
        logger.info(
            f"Starting {level_label} clustering coordinator",
            lookback_days=trace_inputs.lookback_days,
            max_samples=trace_inputs.max_samples,
            analysis_level=str(trace_inputs.analysis_level),
        )

        team_ids = get_allowed_team_ids()

        if not team_ids:
            logger.info("No teams in allowlist")
            return {
                "teams_processed": 0,
                "total_clusters": 0,
                "analysis_level": str(trace_inputs.analysis_level),
            }

        logger.info("Processing teams from allowlist", team_count=len(team_ids), team_ids=team_ids)

        total_clusters = 0
        total_traces = 0
        failed_teams: list[int] = []
        successful_teams: list[int] = []

        max_concurrent = trace_inputs.max_concurrent_teams

        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]

            workflow_handles: list[tuple[int, ChildWorkflowHandle[DailyTraceClusteringWorkflow, ClusteringResult]]] = []
            for team_id in batch:
                handle = await temporalio.workflow.start_child_workflow(
                    DailyTraceClusteringWorkflow.run,
                    ClusteringWorkflowInputs(
                        team_id=team_id,
                        lookback_days=trace_inputs.lookback_days,
                        max_samples=trace_inputs.max_samples,
                        min_k=trace_inputs.min_k,
                        max_k=trace_inputs.max_k,
                        analysis_level=trace_inputs.analysis_level,
                    ),
                    id=f"{constants.GENERATION_CHILD_WORKFLOW_ID_PREFIX}-{team_id}-{temporalio.workflow.now().isoformat()}",
                    execution_timeout=constants.WORKFLOW_EXECUTION_TIMEOUT,
                    retry_policy=constants.COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )
                workflow_handles.append((team_id, handle))

            for team_id, handle in workflow_handles:
                try:
                    workflow_result: ClusteringResult = await handle
                    total_clusters += workflow_result.metrics.num_clusters
                    total_traces += workflow_result.metrics.total_traces_analyzed
                    successful_teams.append(team_id)

                    logger.info(
                        "Completed generation clustering for team",
                        team_id=team_id,
                        generations=workflow_result.metrics.total_traces_analyzed,
                        clusters=workflow_result.metrics.num_clusters,
                    )

                except Exception:
                    logger.exception("Failed to cluster generations for team", team_id=team_id)
                    failed_teams.append(team_id)

        logger.info(
            "Generation clustering coordinator completed",
            teams_processed=len(team_ids),
            teams_succeeded=len(successful_teams),
            teams_failed=len(failed_teams),
            total_generations=total_traces,
            total_clusters=total_clusters,
        )

        return {
            "teams_processed": len(team_ids),
            "teams_succeeded": len(successful_teams),
            "teams_failed": len(failed_teams),
            "failed_team_ids": failed_teams,
            "total_generations": total_traces,
            "total_clusters": total_clusters,
            "analysis_level": str(trace_inputs.analysis_level),
        }
