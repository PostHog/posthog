"""
Coordinator workflow for daily trace clustering.

This workflow discovers teams with trace embeddings and spawns
child workflows to cluster traces for each team.
"""

import dataclasses
from datetime import timedelta
from typing import Any

import structlog
import temporalio

from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.models import ClusteringWorkflowInputs
from posthog.temporal.llm_analytics.trace_clustering.workflow import DailyTraceClusteringWorkflow

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class TraceClusteringCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    lookback_days: int = constants.DEFAULT_LOOKBACK_DAYS
    max_samples: int = constants.DEFAULT_MAX_SAMPLES
    min_k: int = constants.DEFAULT_MIN_K
    max_k: int = constants.DEFAULT_MAX_K
    min_embeddings: int = constants.MIN_TRACES_FOR_CLUSTERING
    max_concurrent_teams: int = constants.DEFAULT_MAX_CONCURRENT_TEAMS


@dataclasses.dataclass
class TeamsWithEmbeddingsResult:
    """Result from querying teams with embeddings."""

    team_ids: list[int]


def query_teams_with_embeddings(lookback_days: int, min_embeddings: int) -> list[int]:
    """
    Query ClickHouse for teams that have trace embeddings in the lookback window.

    Shared logic used by both the coordinator activity and manual trigger script.
    """
    from django.utils import timezone

    from posthog.clickhouse.client.connection import Workload
    from posthog.clickhouse.client.execute import sync_execute

    end_dt = timezone.now()
    start_dt = end_dt - timedelta(days=lookback_days)

    result = sync_execute(
        """
        SELECT
            team_id,
            count(DISTINCT document_id) as embedding_count
        FROM posthog_document_embeddings
        WHERE timestamp >= %(start_dt)s
            AND timestamp < %(end_dt)s
            AND rendering = %(rendering)s
            AND length(embedding) > 0
        GROUP BY team_id
        HAVING embedding_count >= %(min_embeddings)s
        ORDER BY team_id
        """,
        {
            "start_dt": start_dt,
            "end_dt": end_dt,
            "rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
            "min_embeddings": min_embeddings,
        },
        workload=Workload.OFFLINE,
    )
    return [row[0] for row in result]


@temporalio.activity.defn
async def get_teams_with_embeddings_activity(
    inputs: TraceClusteringCoordinatorInputs,
) -> TeamsWithEmbeddingsResult:
    """Query for teams that have trace embeddings in the lookback window."""

    @database_sync_to_async
    def get_teams():
        return query_teams_with_embeddings(inputs.lookback_days, inputs.min_embeddings)

    team_ids = await get_teams()

    # Filter by allowlist if configured
    if constants.ALLOWED_TEAM_IDS:
        original_count = len(team_ids)
        team_ids = [team_id for team_id in team_ids if team_id in constants.ALLOWED_TEAM_IDS]
        logger.info(
            "Filtered teams by allowlist",
            original_count=original_count,
            filtered_count=len(team_ids),
            allowed_teams=constants.ALLOWED_TEAM_IDS,
        )
    else:
        logger.info("Found teams with trace embeddings", team_count=len(team_ids))

    return TeamsWithEmbeddingsResult(team_ids=team_ids)


@temporalio.workflow.defn(name="trace-clustering-coordinator")
class TraceClusteringCoordinatorWorkflow(PostHogWorkflow):
    """
    Coordinator workflow that discovers teams with embeddings and spawns child clustering workflows.

    This runs on a schedule (e.g., daily) and automatically processes all teams
    with sufficient trace embeddings.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TraceClusteringCoordinatorInputs:
        """Parse workflow inputs from string list."""
        return TraceClusteringCoordinatorInputs(
            lookback_days=int(inputs[0]) if len(inputs) > 0 else constants.DEFAULT_LOOKBACK_DAYS,
            max_samples=int(inputs[1]) if len(inputs) > 1 else constants.DEFAULT_MAX_SAMPLES,
            min_k=int(inputs[2]) if len(inputs) > 2 else constants.DEFAULT_MIN_K,
            max_k=int(inputs[3]) if len(inputs) > 3 else constants.DEFAULT_MAX_K,
            min_embeddings=int(inputs[4]) if len(inputs) > 4 else constants.MIN_TRACES_FOR_CLUSTERING,
            max_concurrent_teams=int(inputs[5]) if len(inputs) > 5 else constants.DEFAULT_MAX_CONCURRENT_TEAMS,
        )

    @temporalio.workflow.run
    async def run(self, inputs: TraceClusteringCoordinatorInputs) -> dict[str, Any]:
        """Execute coordinator workflow."""
        logger.info(
            "Starting trace clustering coordinator",
            lookback_days=inputs.lookback_days,
            max_samples=inputs.max_samples,
            min_embeddings=inputs.min_embeddings,
        )

        # Step 1: Get teams with trace embeddings
        result = await temporalio.workflow.execute_activity(
            get_teams_with_embeddings_activity,
            inputs,
            schedule_to_close_timeout=timedelta(minutes=5),
            retry_policy=constants.COORDINATOR_ACTIVITY_RETRY_POLICY,
        )

        if not result.team_ids:
            logger.info("No teams with sufficient embeddings found")
            return {
                "teams_processed": 0,
                "total_clusters": 0,
            }

        # Step 2: Spawn child workflows for each team with concurrency limit
        total_clusters = 0
        total_traces = 0
        failed_teams: list[int] = []
        successful_teams: list[int] = []

        # Process teams in batches for controlled parallelism
        max_concurrent = inputs.max_concurrent_teams
        team_ids = result.team_ids

        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]

            # Start all workflows in batch concurrently
            workflow_handles = []
            for team_id in batch:
                handle = await temporalio.workflow.start_child_workflow(
                    DailyTraceClusteringWorkflow.run,
                    ClusteringWorkflowInputs(
                        team_id=team_id,
                        lookback_days=inputs.lookback_days,
                        max_samples=inputs.max_samples,
                        min_k=inputs.min_k,
                        max_k=inputs.max_k,
                    ),
                    id=f"trace-clustering-team-{team_id}-{temporalio.workflow.now().isoformat()}",
                    execution_timeout=constants.WORKFLOW_EXECUTION_TIMEOUT,
                    retry_policy=constants.COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
                )
                workflow_handles.append((team_id, handle))

            # Wait for all workflows in batch to complete
            for team_id, handle in workflow_handles:
                try:
                    workflow_result = await handle.result()
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
            "Trace clustering coordinator completed",
            teams_processed=len(result.team_ids),
            teams_succeeded=len(successful_teams),
            teams_failed=len(failed_teams),
            total_traces=total_traces,
            total_clusters=total_clusters,
        )

        return {
            "teams_processed": len(result.team_ids),
            "teams_succeeded": len(successful_teams),
            "teams_failed": len(failed_teams),
            "failed_team_ids": failed_teams,
            "total_traces": total_traces,
            "total_clusters": total_clusters,
        }
