"""LLM-based cluster labeling for trace clustering workflow.

This module provides cluster labeling using a LangGraph agent that can
iteratively explore cluster structure and generate high-quality labels.
"""

from datetime import datetime

import numpy as np

from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_clustering.constants import NOISE_CLUSTER_ID
from posthog.temporal.llm_analytics.trace_clustering.data import fetch_trace_summaries
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent import run_labeling_agent
from posthog.temporal.llm_analytics.trace_clustering.labeling_agent.state import ClusterTraceData, TraceMetadata
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel, TraceLabelingMetadata


def generate_cluster_labels(
    team: Team,
    trace_ids: list[str],
    labels: list[int],
    trace_metadata: list[TraceLabelingMetadata],
    centroid_coords_2d: list[list[float]],
    window_start: datetime,
    window_end: datetime,
    batch_run_ids: dict[str, str] | None = None,
) -> dict[int, ClusterLabel]:
    """Generate titles and descriptions for all clusters using the labeling agent.

    The agent has tools to explore cluster structure and iteratively generate
    high-quality, distinctive labels for each cluster.

    Args:
        team: Team object for HogQL queries
        trace_ids: List of all trace IDs in clustering
        labels: Cluster assignments for each trace (-1 = noise/outliers)
        trace_metadata: Precomputed per-trace metadata (x, y, distance, rank)
        centroid_coords_2d: UMAP 2D coordinates for each centroid
        window_start: Start of time window
        window_end: End of time window
        batch_run_ids: Dict mapping trace_id -> batch_run_id for linking to summaries

    Returns:
        Dict mapping cluster_id -> ClusterLabel
    """
    labels_array = np.array(labels)
    unique_cluster_ids = np.unique(labels_array)

    # Build cluster data structure for the agent
    cluster_data = _build_cluster_data(
        trace_ids=trace_ids,
        labels=labels_array,
        trace_metadata=trace_metadata,
        centroid_coords_2d=centroid_coords_2d,
        unique_cluster_ids=unique_cluster_ids,
    )

    # Fetch trace summaries for all traces
    all_trace_summaries = fetch_trace_summaries(
        team=team,
        trace_ids=trace_ids,
        batch_run_ids=batch_run_ids or {},
        window_start=window_start,
        window_end=window_end,
    )

    # Run the labeling agent
    result_labels = run_labeling_agent(
        team_id=team.id,
        cluster_data=cluster_data,
        all_trace_summaries=all_trace_summaries,
    )

    return result_labels


def _build_cluster_data(
    trace_ids: list[str],
    labels: np.ndarray,
    trace_metadata: list[TraceLabelingMetadata],
    centroid_coords_2d: list[list[float]],
    unique_cluster_ids: np.ndarray,
) -> dict[int, ClusterTraceData]:
    """Build the cluster data structure expected by the labeling agent.

    Uses precomputed per-trace metadata to build the cluster structure.
    """
    cluster_data: dict[int, ClusterTraceData] = {}
    centroid_coords = np.array(centroid_coords_2d) if centroid_coords_2d else np.zeros((0, 2))

    # Map non-noise cluster IDs to centroid indices
    non_noise_ids = sorted([int(cid) for cid in unique_cluster_ids if cid != NOISE_CLUSTER_ID])
    cluster_to_centroid_idx = {cid: idx for idx, cid in enumerate(non_noise_ids)}

    for cluster_id in unique_cluster_ids:
        cluster_id_int = int(cluster_id)

        # Get indices of traces in this cluster
        cluster_mask = labels == cluster_id
        cluster_trace_indices = np.where(cluster_mask)[0]
        cluster_size = len(cluster_trace_indices)

        if cluster_size == 0:
            continue

        # Get centroid coordinates
        if cluster_id == NOISE_CLUSTER_ID:
            # For noise cluster, compute mean of noise trace coordinates
            noise_x = np.mean([trace_metadata[i].x for i in cluster_trace_indices])
            noise_y = np.mean([trace_metadata[i].y for i in cluster_trace_indices])
            centroid_x, centroid_y = float(noise_x), float(noise_y)
        else:
            centroid_idx = cluster_to_centroid_idx.get(cluster_id_int)
            if centroid_idx is not None and centroid_idx < len(centroid_coords):
                centroid_x = float(centroid_coords[centroid_idx, 0])
                centroid_y = float(centroid_coords[centroid_idx, 1])
            else:
                # Fallback to mean of cluster trace coordinates
                cluster_x = np.mean([trace_metadata[i].x for i in cluster_trace_indices])
                cluster_y = np.mean([trace_metadata[i].y for i in cluster_trace_indices])
                centroid_x, centroid_y = float(cluster_x), float(cluster_y)

        # Build trace metadata for this cluster using precomputed values
        traces_metadata: dict[str, TraceMetadata] = {}
        for trace_idx in cluster_trace_indices:
            trace_id = trace_ids[trace_idx]
            meta = trace_metadata[trace_idx]
            traces_metadata[trace_id] = {
                "trace_id": trace_id,
                "title": "",  # Will be filled from summaries by the agent
                "rank": meta.rank,
                "distance_to_centroid": meta.distance_to_centroid,
                "x": meta.x,
                "y": meta.y,
            }

        cluster_data[cluster_id_int] = ClusterTraceData(
            cluster_id=cluster_id_int,
            size=cluster_size,
            centroid_x=centroid_x,
            centroid_y=centroid_y,
            traces=traces_metadata,
        )

    return cluster_data
