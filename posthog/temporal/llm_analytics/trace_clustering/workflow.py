"""Daily trace clustering workflow."""

import logging
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.llm_analytics.trace_clustering import constants
    from posthog.temporal.llm_analytics.trace_clustering.activities import (
        determine_optimal_k_activity,
        emit_cluster_events_activity,
        generate_cluster_labels_activity,
        perform_clustering_activity,
        select_traces_for_clustering_activity,
    )
    from posthog.temporal.llm_analytics.trace_clustering.models import ClusteringInputs, ClusteringResult

logger = logging.getLogger(__name__)


@workflow.defn(name="daily-trace-clustering")
class DailyTraceClusteringWorkflow:
    """
    Daily workflow to cluster LLM traces based on their embeddings.

    This workflow:
    1. Queries trace embeddings from the last N days
    2. Samples up to max_samples embeddings
    3. Determines optimal k using silhouette score
    4. Performs k-means clustering
    5. Emits results as $ai_trace_clusters events
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
        start_time = workflow.now()

        logger.info(
            f"🚀 Workflow invoked! Starting trace clustering for team {inputs.team_id}, "
            f"lookback_days={inputs.lookback_days}, max_samples={inputs.max_samples}, "
            f"min_k={inputs.min_k}, max_k={inputs.max_k}"
        )

        # Calculate time window
        if inputs.window_start and inputs.window_end:
            window_start = inputs.window_start
            window_end = inputs.window_end
        else:
            end_dt = workflow.now()
            start_dt = end_dt - timedelta(days=inputs.lookback_days)
            window_start = start_dt.isoformat()
            window_end = end_dt.isoformat()

        # Generate clustering run ID
        clustering_run_id = f"team_{inputs.team_id}_{window_end}"

        # Use shared retry policy for activities
        retry_policy = constants.ACTIVITY_RETRY_POLICY

        # 1. Select trace IDs for clustering (query + sample in one step)
        logger.info(f"Step 1: Selecting up to {inputs.max_samples} trace IDs for window {window_start} to {window_end}")
        trace_ids = await workflow.execute_activity(
            select_traces_for_clustering_activity,
            args=[inputs.team_id, window_start, window_end, inputs.max_samples, None],
            start_to_close_timeout=constants.QUERY_EMBEDDINGS_TIMEOUT,
            retry_policy=retry_policy,
        )

        total_traces = len(trace_ids)
        logger.info(f"Selected {total_traces} trace IDs")

        # Check if we have enough traces
        if total_traces < constants.MIN_TRACES_FOR_CLUSTERING:
            logger.warning(
                f"Insufficient traces for clustering: {total_traces} < {constants.MIN_TRACES_FOR_CLUSTERING}"
            )
            # Return early with empty result
            return ClusteringResult(
                clustering_run_id=clustering_run_id,
                team_id=inputs.team_id,
                timestamp=workflow.now().isoformat(),
                window_start=window_start,
                window_end=window_end,
                total_traces_analyzed=total_traces,
                sampled_traces_count=0,
                optimal_k=0,
                silhouette_score=0.0,
                inertia=0.0,
                clusters=[],
                duration_seconds=(workflow.now() - start_time).total_seconds(),
            )

        sampled_count = total_traces
        logger.info(f"Using {sampled_count} trace IDs")

        # 2. Determine optimal k
        logger.info(f"Step 2: Determining optimal k (range: {inputs.min_k}-{inputs.max_k})")
        optimal_k, k_scores = await workflow.execute_activity(
            determine_optimal_k_activity,
            args=[trace_ids, inputs.team_id, inputs.min_k, inputs.max_k],  # Changed: Pass trace_ids and team_id
            start_to_close_timeout=constants.DETERMINE_OPTIMAL_K_TIMEOUT,
            retry_policy=retry_policy,
        )

        # Get silhouette score for optimal k
        silhouette_score = k_scores.get(optimal_k, 0.0)
        logger.info(f"Optimal k={optimal_k}, silhouette={silhouette_score:.4f}")

        # 3. Perform clustering
        logger.info(f"Step 3: Performing k-means clustering with k={optimal_k}")
        labels, centroids, inertia = await workflow.execute_activity(
            perform_clustering_activity,
            args=[trace_ids, inputs.team_id, optimal_k],  # Changed: Pass trace_ids and team_id
            start_to_close_timeout=constants.PERFORM_CLUSTERING_TIMEOUT,
            retry_policy=retry_policy,
        )
        logger.info(f"Clustering complete, inertia={inertia:.2f}")

        # 4. Generate cluster labels
        logger.info(f"Step 4: Generating cluster labels using LLM")
        cluster_labels = await workflow.execute_activity(
            generate_cluster_labels_activity,
            args=[
                inputs.team_id,
                trace_ids,  # Changed: Pass trace_ids
                labels,
                centroids,
                optimal_k,
                constants.TRACES_PER_CLUSTER_FOR_LABELING,  # Changed: Constant name
            ],
            start_to_close_timeout=constants.GENERATE_LABELS_TIMEOUT,
            retry_policy=retry_policy,
        )
        logger.info(f"Generated labels for {len(cluster_labels)} clusters")

        # 5. Emit cluster events
        logger.info(f"Step 5: Emitting cluster events")
        await workflow.execute_activity(
            emit_cluster_events_activity,
            args=[
                inputs.team_id,
                clustering_run_id,
                window_start,
                window_end,
                total_traces,
                sampled_count,
                optimal_k,
                silhouette_score,
                inertia,
                labels,
                centroids,
                trace_ids,  # Changed: Pass trace_ids
                cluster_labels,
            ],
            start_to_close_timeout=constants.EMIT_EVENTS_TIMEOUT,
            retry_policy=retry_policy,
        )

        # Build result
        clusters = []
        for cluster_id in range(optimal_k):
            cluster_size = sum(1 for label in labels if label == cluster_id)
            cluster_trace_ids = [trace_ids[i] for i, label in enumerate(labels) if label == cluster_id]

            from posthog.temporal.llm_analytics.trace_clustering.models import Cluster

            clusters.append(
                Cluster(
                    cluster_id=cluster_id,
                    size=cluster_size,
                    trace_ids=cluster_trace_ids,
                )
            )

        duration = (workflow.now() - start_time).total_seconds()

        logger.info(
            f"Trace clustering completed for team {inputs.team_id}: "
            f"{optimal_k} clusters from {sampled_count} traces in {duration:.2f}s"
        )

        return ClusteringResult(
            clustering_run_id=clustering_run_id,
            team_id=inputs.team_id,
            timestamp=workflow.now().isoformat(),
            window_start=window_start,
            window_end=window_end,
            total_traces_analyzed=total_traces,
            sampled_traces_count=sampled_count,
            optimal_k=optimal_k,
            silhouette_score=silhouette_score,
            inertia=inertia,
            clusters=clusters,
            duration_seconds=duration,
        )
