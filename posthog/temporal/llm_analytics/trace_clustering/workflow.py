"""Daily trace clustering workflow."""

import asyncio
import logging

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.llm_analytics.trace_clustering.clustering import perform_clustering
    from posthog.temporal.llm_analytics.trace_clustering.models import ClusteringInputs, ClusteringResult

logger = logging.getLogger(__name__)


@activity.defn
async def perform_clustering_activity(inputs: ClusteringInputs) -> ClusteringResult:
    """Activity wrapper for the main clustering function.

    This activity executes the complete clustering pipeline which internally:
    1. Queries and samples trace IDs
    2. Fetches embeddings from ClickHouse
    3. Determines optimal k using silhouette score
    4. Performs k-means clustering
    5. Generates LLM-based cluster labels
    6. Emits results as $ai_trace_clusters events

    Args:
        inputs: ClusteringInputs with team_id and parameters

    Returns:
        ClusteringResult with clustering metrics and cluster info
    """
    return await asyncio.to_thread(perform_clustering, inputs)


@workflow.defn(name="daily-trace-clustering")
class DailyTraceClusteringWorkflow:
    """
    Daily workflow to cluster LLM traces based on their embeddings.

    This workflow is a thin orchestration layer that:
    1. Receives clustering parameters
    2. Executes the clustering activity
    3. Returns results

    All the heavy lifting (data fetching, clustering, labeling, event emission)
    happens within the single activity to avoid passing large data through the workflow.
    """

    @workflow.run
    async def run(self, inputs: ClusteringInputs) -> ClusteringResult:
        """
        Execute the daily trace clustering workflow.

        Args:
            inputs: ClusteringInputs with team_id and parameters

        Returns:
            ClusteringResult with clustering metrics and cluster info
        """
        from posthog.temporal.llm_analytics.trace_clustering import constants

        inputs = ClusteringInputs(
            team_id=inputs.team_id,
            current_time=workflow.now().isoformat(),
            lookback_days=inputs.lookback_days,
            max_samples=inputs.max_samples,
            min_k=inputs.min_k,
            max_k=inputs.max_k,
            window_start=inputs.window_start,
            window_end=inputs.window_end,
        )

        result = await workflow.execute_activity(
            perform_clustering_activity,
            args=[inputs],
            start_to_close_timeout=constants.CLUSTERING_ACTIVITY_TIMEOUT,
            retry_policy=constants.ACTIVITY_RETRY_POLICY,
        )

        return result
