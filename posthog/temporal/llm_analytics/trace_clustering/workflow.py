"""Daily trace clustering workflow."""

from datetime import timedelta

from temporalio import workflow

from posthog.temporal.llm_analytics.trace_clustering.activities import (
    emit_cluster_events_activity,
    generate_cluster_labels_activity,
    perform_clustering_compute_activity,
)
from posthog.temporal.llm_analytics.trace_clustering.constants import (
    COMPUTE_ACTIVITY_RETRY_POLICY,
    COMPUTE_ACTIVITY_TIMEOUT,
    EMIT_ACTIVITY_RETRY_POLICY,
    EMIT_ACTIVITY_TIMEOUT,
    LLM_ACTIVITY_RETRY_POLICY,
    NOISE_CLUSTER_ID,
    WORKFLOW_NAME,
)
from posthog.temporal.llm_analytics.trace_clustering.models import (
    ClusteringActivityInputs,
    ClusteringComputeResult,
    ClusteringParams,
    ClusteringResult,
    ClusteringWorkflowInputs,
    EmitEventsActivityInputs,
    GenerateLabelsActivityInputs,
    TraceLabelingMetadata,
)


def _compute_item_labeling_metadata(
    compute_result: "ClusteringComputeResult",
) -> list["TraceLabelingMetadata"]:
    """Compute per-item metadata for the labeling activity.

    Extracts each item's distance to its own cluster centroid and computes
    rank within cluster. This avoids passing the full O(n × k) distances matrix.

    Returns:
        List of TraceLabelingMetadata, one per item (same order as items)
    """
    import numpy as np

    labels = np.array(compute_result.labels)
    distances = np.array(compute_result.distances)
    coords_2d = np.array(compute_result.coords_2d)

    n_items = len(labels)
    unique_labels = np.unique(labels)

    # Map non-noise cluster IDs to distance matrix column indices
    non_noise_ids = sorted([cid for cid in unique_labels if cid != NOISE_CLUSTER_ID])
    cluster_to_col = {cid: idx for idx, cid in enumerate(non_noise_ids)}

    # Compute per-item distance to own centroid
    item_distances = np.zeros(n_items)
    for i, label in enumerate(labels):
        if label == NOISE_CLUSTER_ID:
            # For noise, we'll compute distance to noise cluster mean later
            item_distances[i] = 0.0
        else:
            col = cluster_to_col.get(label, 0)
            if col < distances.shape[1]:
                item_distances[i] = distances[i, col]

    # Handle noise cluster: compute distance to mean of noise items
    noise_mask = labels == NOISE_CLUSTER_ID
    if noise_mask.any():
        noise_coords = coords_2d[noise_mask]
        noise_centroid = noise_coords.mean(axis=0)
        noise_distances = np.linalg.norm(noise_coords - noise_centroid, axis=1)
        item_distances[noise_mask] = noise_distances

    # Compute ranks within each cluster
    ranks = np.zeros(n_items, dtype=int)
    for cluster_id in unique_labels:
        cluster_mask = labels == cluster_id
        cluster_indices = np.where(cluster_mask)[0]
        cluster_dists = item_distances[cluster_indices]

        # Rank by distance (1 = closest to centroid)
        order = np.argsort(cluster_dists)
        cluster_ranks = np.empty_like(order)
        cluster_ranks[order] = np.arange(1, len(order) + 1)
        ranks[cluster_indices] = cluster_ranks

    # Build metadata list
    metadata = []
    for i in range(n_items):
        metadata.append(
            TraceLabelingMetadata(
                x=float(coords_2d[i, 0]),
                y=float(coords_2d[i, 1]),
                distance_to_centroid=float(item_distances[i]),
                rank=int(ranks[i]),
            )
        )

    return metadata


@workflow.defn(name=WORKFLOW_NAME)
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

        # Calculate window from workflow time (deterministic for replays)
        now = workflow.now()
        window_end = now.isoformat()
        window_start = (now - timedelta(days=inputs.lookback_days)).isoformat()

        # Activity 1: Compute clustering (fetch embeddings, cluster, distances)
        compute_result = await workflow.execute_activity(
            perform_clustering_compute_activity,
            args=[
                ClusteringActivityInputs(
                    team_id=inputs.team_id,
                    window_start=window_start,
                    window_end=window_end,
                    analysis_level=inputs.analysis_level,
                    max_samples=inputs.max_samples,
                    min_k=inputs.min_k,
                    max_k=inputs.max_k,
                    embedding_normalization=inputs.embedding_normalization,
                    dimensionality_reduction_method=inputs.dimensionality_reduction_method,
                    dimensionality_reduction_ndims=inputs.dimensionality_reduction_ndims,
                    run_label=inputs.run_label,
                    clustering_method=inputs.clustering_method,
                    clustering_method_params=inputs.clustering_method_params,
                    visualization_method=inputs.visualization_method,
                    trace_filters=inputs.trace_filters,
                )
            ],
            start_to_close_timeout=COMPUTE_ACTIVITY_TIMEOUT,
            retry_policy=COMPUTE_ACTIVITY_RETRY_POLICY,
        )

        # Compute per-item metadata for labeling (O(n) instead of O(n × k))
        item_metadata = _compute_item_labeling_metadata(compute_result)

        # Activity 2: Generate LLM labels (longer timeout for agent run)
        labels_result = await workflow.execute_activity(
            generate_cluster_labels_activity,
            args=[
                GenerateLabelsActivityInputs(
                    team_id=inputs.team_id,
                    items=compute_result.items,
                    labels=compute_result.labels,
                    item_metadata=item_metadata,
                    centroid_coords_2d=compute_result.centroid_coords_2d,
                    window_start=window_start,
                    window_end=window_end,
                    analysis_level=compute_result.analysis_level,
                    batch_run_ids=compute_result.batch_run_ids,
                )
            ],
            start_to_close_timeout=timedelta(seconds=600),  # 10 minutes for agent run
            retry_policy=LLM_ACTIVITY_RETRY_POLICY,
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
                    items=compute_result.items,
                    labels=compute_result.labels,
                    centroids=compute_result.centroids,
                    distances=compute_result.distances,
                    cluster_labels=labels_result.cluster_labels,
                    coords_2d=compute_result.coords_2d,
                    centroid_coords_2d=compute_result.centroid_coords_2d,
                    analysis_level=compute_result.analysis_level,
                    batch_run_ids=compute_result.batch_run_ids,
                    clustering_params=ClusteringParams(
                        clustering_method=inputs.clustering_method,
                        clustering_method_params=inputs.clustering_method_params,
                        embedding_normalization=inputs.embedding_normalization,
                        dimensionality_reduction_method=inputs.dimensionality_reduction_method,
                        dimensionality_reduction_ndims=inputs.dimensionality_reduction_ndims,
                        visualization_method=inputs.visualization_method,
                        max_samples=inputs.max_samples,
                    ),
                )
            ],
            start_to_close_timeout=EMIT_ACTIVITY_TIMEOUT,
            retry_policy=EMIT_ACTIVITY_RETRY_POLICY,
        )

        return result
