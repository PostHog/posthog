"""
Coordinator workflow for daily trace clustering.

This workflow discovers teams dynamically via the team discovery activity
and spawns child workflows to cluster traces for each team.

Uses continue_as_new after each batch to keep the workflow history bounded
(Temporal has a 50K event limit per execution).

Per-team child workflows handle the case where a team has no traces
gracefully (returning empty results).
"""

import dataclasses
from datetime import timedelta
from typing import Any

import structlog
import temporalio
from temporalio.workflow import ChildWorkflowHandle

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.constants import (
    CHILD_WORKFLOW_ID_PREFIX,
    COORDINATOR_WORKFLOW_NAME,
    GENERATION_CHILD_WORKFLOW_ID_PREFIX,
)
from posthog.temporal.llm_analytics.trace_clustering.models import (
    AnalysisLevel,
    ClusteringResult,
    ClusteringWorkflowInputs,
)
from posthog.temporal.llm_analytics.trace_clustering.workflow import DailyTraceClusteringWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.llm_analytics.coordinator_metrics import (
        increment_team_failed,
        increment_team_succeeded,
        record_teams_discovered,
    )
    from posthog.temporal.llm_analytics.shared_activities import (
        FetchAllClusteringFiltersInput,
        fetch_all_clustering_filters_activity,
    )
    from posthog.temporal.llm_analytics.team_discovery import (
        DISCOVERY_ACTIVITY_RETRY_POLICY,
        DISCOVERY_ACTIVITY_TIMEOUT,
        GUARANTEED_TEAM_IDS,
        SAMPLE_PERCENTAGE,
        TeamDiscoveryInput,
        get_team_ids_for_llm_analytics,
    )

logger = structlog.get_logger(__name__)


def _empty_clustering_results() -> dict[str, Any]:
    return {
        "teams_succeeded": 0,
        "teams_failed": 0,
        "failed_team_ids": [],
        "total_items": 0,
        "total_clusters": 0,
    }


@dataclasses.dataclass
class TraceClusteringCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    analysis_level: AnalysisLevel = "trace"  # "trace" or "generation"
    lookback_days: int = constants.DEFAULT_LOOKBACK_DAYS
    max_samples: int = constants.DEFAULT_MAX_SAMPLES
    min_k: int = constants.DEFAULT_MIN_K
    max_k: int = constants.DEFAULT_MAX_K
    max_concurrent_teams: int = constants.DEFAULT_MAX_CONCURRENT_TEAMS
    # Fields used by continue_as_new to carry state across continuations.
    # When remaining_team_ids is set, team discovery is skipped.
    remaining_team_ids: list[int] | None = None
    per_team_filters: dict[str, list[dict[str, Any]]] | None = None
    results_so_far: dict[str, Any] | None = None


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class TraceClusteringCoordinatorWorkflow(PostHogWorkflow):
    """
    Coordinator workflow that discovers teams dynamically and spawns child
    workflows for each team. Teams with no traces will complete quickly
    with empty results.

    Uses continue_as_new to keep history bounded when processing many teams.
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

        # Phase A: resolve teams and filters.
        # On continuation legs, these are passed in directly to avoid
        # re-running expensive ClickHouse queries.
        if inputs.remaining_team_ids is not None:
            team_ids = inputs.remaining_team_ids
            # Temporal JSON serialization converts int dict keys to strings
            per_team_filters: dict[int, list[dict[str, Any]]] = (
                {int(k): v for k, v in inputs.per_team_filters.items()} if inputs.per_team_filters else {}
            )
            results_so_far = inputs.results_so_far or _empty_clustering_results()
            logger.info(
                "Resuming clustering coordinator after continue_as_new",
                remaining_teams=len(team_ids),
                teams_succeeded_so_far=results_so_far["teams_succeeded"],
            )
        else:
            logger.info(
                "Starting trace clustering coordinator",
                analysis_level=inputs.analysis_level,
                lookback_days=inputs.lookback_days,
                max_samples=inputs.max_samples,
            )

            # Discover teams dynamically via activity, falling back to guaranteed
            # teams if the activity fails (e.g. ClickHouse timeout).
            try:
                team_ids = await temporalio.workflow.execute_activity(
                    get_team_ids_for_llm_analytics,
                    TeamDiscoveryInput(sample_percentage=SAMPLE_PERCENTAGE),
                    start_to_close_timeout=DISCOVERY_ACTIVITY_TIMEOUT,
                    retry_policy=DISCOVERY_ACTIVITY_RETRY_POLICY,
                )
            except Exception:
                logger.warning("Team discovery activity failed, falling back to guaranteed teams", exc_info=True)
                team_ids = sorted(GUARANTEED_TEAM_IDS)

            logger.info("Processing discovered teams", team_count=len(team_ids), team_ids=team_ids)
            record_teams_discovered(len(team_ids), "clustering", inputs.analysis_level)

            # Fetch user-configured event filters for all teams
            try:
                per_team_filters = await temporalio.workflow.execute_activity(
                    fetch_all_clustering_filters_activity,
                    FetchAllClusteringFiltersInput(team_ids=team_ids),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
                )
            except Exception:
                logger.warning("Failed to fetch clustering filters, proceeding without filters", exc_info=True)
                per_team_filters = {}

            results_so_far = _empty_clustering_results()

        # Phase B: process teams in batches, using continue_as_new to keep
        # the workflow history bounded.
        max_concurrent = inputs.max_concurrent_teams
        child_id_prefix = (
            GENERATION_CHILD_WORKFLOW_ID_PREFIX if inputs.analysis_level == "generation" else CHILD_WORKFLOW_ID_PREFIX
        )

        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]

            # Start all workflows in batch concurrently
            workflow_handles: list[tuple[int, ChildWorkflowHandle[DailyTraceClusteringWorkflow, ClusteringResult]]] = []
            for team_id in batch:
                event_filters = per_team_filters.get(team_id, [])
                handle = await temporalio.workflow.start_child_workflow(
                    DailyTraceClusteringWorkflow.run,
                    ClusteringWorkflowInputs(
                        team_id=team_id,
                        analysis_level=inputs.analysis_level,
                        lookback_days=inputs.lookback_days,
                        max_samples=inputs.max_samples,
                        min_k=inputs.min_k,
                        max_k=inputs.max_k,
                        event_filters=event_filters,
                    ),
                    id=f"{child_id_prefix}-{team_id}-{temporalio.workflow.now().isoformat()}",
                    execution_timeout=constants.WORKFLOW_EXECUTION_TIMEOUT,
                    retry_policy=constants.COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.TERMINATE,
                )
                workflow_handles.append((team_id, handle))

            # Wait for all workflows in batch to complete
            for team_id, handle in workflow_handles:
                try:
                    workflow_result: ClusteringResult = await handle
                    results_so_far["total_clusters"] += workflow_result.metrics.num_clusters
                    results_so_far["total_items"] += workflow_result.metrics.total_items_analyzed
                    results_so_far["teams_succeeded"] += 1
                    increment_team_succeeded("clustering", inputs.analysis_level)

                    logger.info(
                        "Completed clustering for team",
                        team_id=team_id,
                        items=workflow_result.metrics.total_items_analyzed,
                        clusters=workflow_result.metrics.num_clusters,
                    )

                except Exception:
                    logger.exception("Failed to cluster team", team_id=team_id)
                    results_so_far["failed_team_ids"].append(team_id)
                    results_so_far["teams_failed"] += 1
                    increment_team_failed("clustering", inputs.analysis_level)

            # After each batch, check if Temporal suggests continuing as new
            # to keep the history size bounded.
            remaining = team_ids[batch_start + max_concurrent :]
            if remaining and temporalio.workflow.info().is_continue_as_new_suggested():
                logger.info(
                    "Continuing as new to keep history bounded",
                    teams_remaining=len(remaining),
                    teams_processed_this_leg=batch_start + len(batch),
                )
                # Serialize per_team_filters with string keys for Temporal JSON
                serializable_filters = {str(k): v for k, v in per_team_filters.items()}
                temporalio.workflow.continue_as_new(
                    TraceClusteringCoordinatorInputs(
                        analysis_level=inputs.analysis_level,
                        lookback_days=inputs.lookback_days,
                        max_samples=inputs.max_samples,
                        min_k=inputs.min_k,
                        max_k=inputs.max_k,
                        max_concurrent_teams=inputs.max_concurrent_teams,
                        remaining_team_ids=remaining,
                        per_team_filters=serializable_filters,
                        results_so_far=results_so_far,
                    )
                )

        # Final leg: return accumulated results
        total_teams = results_so_far["teams_succeeded"] + results_so_far["teams_failed"]
        logger.info(
            "Trace clustering coordinator completed",
            teams_processed=total_teams,
            teams_succeeded=results_so_far["teams_succeeded"],
            teams_failed=results_so_far["teams_failed"],
            total_items=results_so_far["total_items"],
            total_clusters=results_so_far["total_clusters"],
        )

        return {
            "teams_processed": total_teams,
            "teams_succeeded": results_so_far["teams_succeeded"],
            "teams_failed": results_so_far["teams_failed"],
            "failed_team_ids": results_so_far["failed_team_ids"],
            "total_items": results_so_far["total_items"],
            "total_clusters": results_so_far["total_clusters"],
        }
