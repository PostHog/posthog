"""Event emission for clustering results.

This module contains functions for emitting clustering results to ClickHouse:
- Build cluster data structures with centroids and distances
- Emit $ai_trace_clusters event with all clustering metadata
- Handle noise/outlier cluster from HDBSCAN (cluster_id = -1)
"""

import uuid
import dataclasses
from typing import TypedDict

from django.utils.dateparse import parse_datetime

import numpy as np

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.constants import NOISE_CLUSTER_ID
from posthog.temporal.llm_analytics.trace_clustering.data import fetch_item_summaries
from posthog.temporal.llm_analytics.trace_clustering.models import (
    AnalysisLevel,
    ClusterData,
    ClusteringParams,
    ClusterItem,
    ClusterLabel,
    ItemBatchRunIds,
    TraceClusterMetadata,
)


class _ItemDistanceData(TypedDict):
    """Internal type for item distance data during cluster building."""

    trace_id: str  # Always set - the trace ID (or parent trace for generations)
    generation_id: str | None  # Only set for generation-level clustering
    distance_to_centroid: float
    x: float
    y: float
    timestamp: str


def emit_cluster_events(
    team_id: int,
    clustering_run_id: str,
    window_start: str,
    window_end: str,
    labels: list[int],
    centroids: list[list[float]],
    items: list[ClusterItem],
    distances_matrix: np.ndarray,
    cluster_labels: dict[int, ClusterLabel],
    coords_2d: np.ndarray,
    centroid_coords_2d: np.ndarray,
    batch_run_ids: ItemBatchRunIds | None = None,
    clustering_params: ClusteringParams | None = None,
    analysis_level: AnalysisLevel = "trace",
) -> list[ClusterData]:
    """Emit $ai_trace_clusters or $ai_generation_clusters event to ClickHouse.

    Creates a single event containing all clusters with trace/generation IDs, centroids, and LLM-generated labels.
    The UI can fetch metadata for individual traces/generations as needed.

    Args:
        team_id: Team ID
        clustering_run_id: Unique ID for this clustering run
        window_start: Start of time window (ISO format)
        window_end: End of time window (ISO format)
        labels: Cluster assignments
        centroids: Cluster centroids (center points in embedding space)
        items: All items being clustered with explicit trace_id and generation_id
        distances_matrix: Pre-computed distances from each item to all centroids
        cluster_labels: Dict mapping cluster_id -> ClusterLabel
        coords_2d: UMAP 2D coordinates for each item, shape (n_items, 2)
        centroid_coords_2d: UMAP 2D coordinates for each centroid, shape (n_clusters, 2)
        batch_run_ids: Dict mapping item_id -> batch_run_id for linking to summaries
        clustering_params: Parameters used for this clustering run
        analysis_level: "trace" or "generation" - determines which event type to emit

    Returns:
        List of ClusterData objects emitted
    """
    # Select event name based on analysis_level
    event_name = constants.EVENT_NAME_GENERATION if analysis_level == "generation" else constants.EVENT_NAME
    team = Team.objects.get(id=team_id)
    num_clusters = len(centroids)

    # Get item IDs for summaries lookup (generation_id for generation-level, trace_id for trace-level)
    item_ids = [item.generation_id if item.generation_id else item.trace_id for item in items]

    # Fetch summaries to get timestamps for efficient linking
    window_start_dt = parse_datetime(window_start)
    window_end_dt = parse_datetime(window_end)
    if window_start_dt is None or window_end_dt is None:
        raise ValueError(f"Invalid datetime format: window_start={window_start}, window_end={window_end}")

    summaries = fetch_item_summaries(
        team=team,
        item_ids=item_ids,
        batch_run_ids=batch_run_ids or {},
        window_start=window_start_dt,
        window_end=window_end_dt,
        analysis_level=analysis_level,
    )

    # Extract timestamps from summaries
    item_timestamps: dict[str, str] = {
        item_id: summary.get("trace_timestamp", "") for item_id, summary in summaries.items()
    }

    # Build clusters array with centroids and item distances
    clusters = _build_cluster_data(
        num_clusters=num_clusters,
        labels=labels,
        items=items,
        distances_matrix=distances_matrix,
        centroids=centroids,
        cluster_labels=cluster_labels,
        coords_2d=coords_2d,
        centroid_coords_2d=centroid_coords_2d,
        item_timestamps=item_timestamps,
    )

    # Build and emit event
    event_uuid = uuid.uuid4()

    properties = {
        "$ai_clustering_run_id": clustering_run_id,
        "$ai_clustering_level": analysis_level,
        "$ai_window_start": window_start,
        "$ai_window_end": window_end,
        "$ai_total_items_analyzed": len(items),
        "$ai_clusters": [dataclasses.asdict(c) for c in clusters],
    }

    # Add clustering params if provided
    if clustering_params:
        properties["$ai_clustering_params"] = dataclasses.asdict(clustering_params)

    create_event(
        event_uuid=event_uuid,
        event=event_name,
        team=team,
        distinct_id=f"clustering_{analysis_level}_{team_id}",
        properties=properties,
    )

    return clusters


def _build_cluster_data(
    num_clusters: int,
    labels: list[int],
    items: list[ClusterItem],
    distances_matrix: np.ndarray,
    centroids: list[list[float]],
    cluster_labels: dict[int, ClusterLabel],
    coords_2d: np.ndarray,
    centroid_coords_2d: np.ndarray,
    item_timestamps: dict[str, str],
) -> list[ClusterData]:
    """Build cluster data structure with items and metadata.

    Handles both regular clusters and noise/outlier cluster (cluster_id = -1).
    Noise cluster items use minimum distance to any centroid.

    Args:
        num_clusters: Number of regular clusters (excludes noise)
        labels: Cluster assignments for each item (-1 = noise)
        items: All items being clustered with explicit trace_id and generation_id
        distances_matrix: Distance matrix (num_items x num_clusters)
        centroids: Cluster centroids (only for regular clusters)
        cluster_labels: Dict mapping cluster_id -> ClusterLabel
        coords_2d: UMAP 2D coordinates for each item, shape (n_items, 2)
        centroid_coords_2d: UMAP 2D coordinates for each centroid, shape (n_clusters, 2)
        item_timestamps: Dict mapping item_id -> timestamp (ISO format)

    Returns:
        List of ClusterData objects (regular clusters first, then noise if present)
    """
    clusters = []
    unique_labels = sorted(set(labels))

    # Process regular clusters first (non-negative IDs)
    for cluster_id in [cid for cid in unique_labels if cid >= 0]:
        cluster_item_data: list[_ItemDistanceData] = []
        for i, label in enumerate(labels):
            if label == cluster_id:
                item = items[i]
                # For timestamps lookup, use generation_id if present, else trace_id
                item_key = item.generation_id if item.generation_id else item.trace_id
                cluster_item_data.append(
                    {
                        "trace_id": item.trace_id,
                        "generation_id": item.generation_id,
                        "distance_to_centroid": float(distances_matrix[i][cluster_id]),
                        "x": float(coords_2d[i][0]),
                        "y": float(coords_2d[i][1]),
                        "timestamp": item_timestamps.get(item_key, ""),
                    }
                )

        cluster_item_data.sort(key=lambda x: x["distance_to_centroid"])

        # Key by trace_id for trace-level, generation_id for generation-level
        traces_dict: dict[str, TraceClusterMetadata] = {}
        for rank, t in enumerate(cluster_item_data):
            key = t["generation_id"] if t["generation_id"] else t["trace_id"]
            metadata = TraceClusterMetadata(
                distance_to_centroid=t["distance_to_centroid"],
                rank=rank,
                x=t["x"],
                y=t["y"],
                timestamp=t["timestamp"],
                trace_id=t["trace_id"],
                generation_id=t["generation_id"],
            )
            traces_dict[key] = metadata

        if cluster_id in cluster_labels:
            title = cluster_labels[cluster_id].title
            description = cluster_labels[cluster_id].description
        else:
            title = f"Cluster {cluster_id}"
            description = ""

        clusters.append(
            ClusterData(
                cluster_id=cluster_id,
                size=len(traces_dict),
                title=title,
                description=description,
                traces=traces_dict,
                centroid=centroids[cluster_id],
                centroid_x=float(centroid_coords_2d[cluster_id][0]),
                centroid_y=float(centroid_coords_2d[cluster_id][1]),
            )
        )

    # Process noise cluster if present
    if NOISE_CLUSTER_ID in unique_labels:
        noise_item_data: list[_ItemDistanceData] = []
        noise_coords = []

        for i, label in enumerate(labels):
            if label == NOISE_CLUSTER_ID:
                item = items[i]
                item_key = item.generation_id if item.generation_id else item.trace_id
                # For noise points, use minimum distance to any centroid
                if distances_matrix.shape[1] > 0:
                    min_distance = float(np.min(distances_matrix[i]))
                else:
                    min_distance = 0.0

                noise_item_data.append(
                    {
                        "trace_id": item.trace_id,
                        "generation_id": item.generation_id,
                        "distance_to_centroid": min_distance,
                        "x": float(coords_2d[i][0]),
                        "y": float(coords_2d[i][1]),
                        "timestamp": item_timestamps.get(item_key, ""),
                    }
                )
                noise_coords.append(coords_2d[i])

        # Sort by distance (most anomalous first - highest min distance)
        noise_item_data.sort(key=lambda x: x["distance_to_centroid"], reverse=True)

        noise_traces_dict: dict[str, TraceClusterMetadata] = {}
        for rank, t in enumerate(noise_item_data):
            key = t["generation_id"] if t["generation_id"] else t["trace_id"]
            metadata = TraceClusterMetadata(
                distance_to_centroid=t["distance_to_centroid"],
                rank=rank,
                x=t["x"],
                y=t["y"],
                timestamp=t["timestamp"],
                trace_id=t["trace_id"],
                generation_id=t["generation_id"],
            )
            noise_traces_dict[key] = metadata

        # Compute centroid as mean of noise points for visualization
        if noise_coords:
            noise_centroid_2d = np.mean(noise_coords, axis=0)
            centroid_x = float(noise_centroid_2d[0])
            centroid_y = float(noise_centroid_2d[1])
        else:
            centroid_x = 0.0
            centroid_y = 0.0

        if NOISE_CLUSTER_ID in cluster_labels:
            title = cluster_labels[NOISE_CLUSTER_ID].title
            description = cluster_labels[NOISE_CLUSTER_ID].description
        else:
            title = "Outliers"
            description = "Items that did not fit into any cluster"

        clusters.append(
            ClusterData(
                cluster_id=NOISE_CLUSTER_ID,
                size=len(noise_traces_dict),
                title=title,
                description=description,
                traces=noise_traces_dict,
                centroid=[],  # No actual centroid for noise cluster
                centroid_x=centroid_x,
                centroid_y=centroid_y,
            )
        )

    return clusters
