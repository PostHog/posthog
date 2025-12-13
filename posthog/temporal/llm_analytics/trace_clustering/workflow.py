"""Daily trace clustering workflow."""

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.llm_analytics.trace_clustering.activities import (
        emit_cluster_events_activity,
        generate_cluster_labels_activity,
        perform_clustering_compute_activity,
    )
    from posthog.temporal.llm_analytics.trace_clustering.models import (
        ClusteringActivityInputs,
        ClusteringResult,
        ClusteringWorkflowInputs,
        EmitEventsActivityInputs,
        GenerateLabelsActivityInputs,
    )


@workflow.defn(name="daily-trace-clustering")
class DailyTraceClusteringWorkflow:
    """
    Daily workflow to cluster LLM traces based on their embeddings.

    This workflow orchestrates 3 activities:
    1. Compute: Fetch embeddings, perform k-means clustering, compute distances
    2. Label: Generate LLM-based cluster labels (long timeout for API call)
    3. Emit: Write clustering results to ClickHouse

    The workflow calculates window_start/window_end from lookback_days and
    passes them to activities. Embeddings (~30+ MB) stay within Activity 1,
    only ~250 KB of results are passed between activities.
    """

    @workflow.run
    async def run(self, inputs: ClusteringWorkflowInputs) -> ClusteringResult:
        """
        Execute the daily trace clustering workflow.

        Args:
            inputs: ClusteringWorkflowInputs with team_id and lookback_days

        Returns:
            ClusteringResult with clustering metrics and cluster info
        """
        from posthog.temporal.llm_analytics.trace_clustering import constants

        # Calculate window from workflow time (deterministic for replays)
        now = workflow.now()
        window_end = now.isoformat()
        window_start = (now - timedelta(days=inputs.lookback_days)).isoformat()

        # Activity 1: Compute clustering (fetch embeddings, k-means, distances)
        compute_result = await workflow.execute_activity(
            perform_clustering_compute_activity,
            args=[
                ClusteringActivityInputs(
                    team_id=inputs.team_id,
                    window_start=window_start,
                    window_end=window_end,
                    max_samples=inputs.max_samples,
                    min_k=inputs.min_k,
                    max_k=inputs.max_k,
                )
            ],
            start_to_close_timeout=constants.COMPUTE_ACTIVITY_TIMEOUT,
            retry_policy=constants.COMPUTE_ACTIVITY_RETRY_POLICY,
        )

        # Activity 2: Generate LLM labels (longer timeout for API call)
        labels_result = await workflow.execute_activity(
            generate_cluster_labels_activity,
            args=[
                GenerateLabelsActivityInputs(
                    team_id=inputs.team_id,
                    labels=compute_result.labels,
                    representative_trace_ids=compute_result.representative_trace_ids,
                    window_start=window_start,
                    window_end=window_end,
                )
            ],
            start_to_close_timeout=constants.LLM_ACTIVITY_TIMEOUT,
            retry_policy=constants.LLM_ACTIVITY_RETRY_POLICY,
        )

        # Activity 3: Emit events to ClickHouse
        result = await workflow.execute_activity(
            emit_cluster_events_activity,
            args=[
                EmitEventsActivityInputs(
                    team_id=inputs.team_id,
                    clustering_run_id=compute_result.clustering_run_id,
                    window_start=window_start,
                    window_end=window_end,
                    trace_ids=compute_result.trace_ids,
                    labels=compute_result.labels,
                    centroids=compute_result.centroids,
                    distances=compute_result.distances,
                    cluster_labels=labels_result.cluster_labels,
                )
            ],
            start_to_close_timeout=constants.EMIT_ACTIVITY_TIMEOUT,
            retry_policy=constants.EMIT_ACTIVITY_RETRY_POLICY,
        )

        return result
