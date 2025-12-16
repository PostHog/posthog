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
from posthog.temporal.llm_analytics.trace_clustering.data import fetch_trace_summaries
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterData, ClusteringParams, ClusterLabel, TraceId


class _TraceDistanceData(TypedDict):
    """Internal type for trace distance data during cluster building."""

    trace_id: str
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
    trace_ids: list[TraceId],
    distances_matrix: np.ndarray,
    cluster_labels: dict[int, ClusterLabel],
    coords_2d: np.ndarray,
    centroid_coords_2d: np.ndarray,
    batch_run_ids: dict[str, str] | None = None,
    clustering_params: ClusteringParams | None = None,
) -> list[ClusterData]:
    """Emit $ai_trace_clusters event to ClickHouse.

    Creates a single event containing all clusters with trace IDs, centroids, and LLM-generated labels.
    The UI can fetch metadata for individual traces as needed.

    Args:
        team_id: Team ID
        clustering_run_id: Unique ID for this clustering run
        window_start: Start of time window (ISO format)
        window_end: End of time window (ISO format)
        labels: Cluster assignments
        centroids: Cluster centroids (center points in embedding space)
        trace_ids: All trace IDs being clustered
        distances_matrix: Pre-computed distances from each trace to all centroids
        cluster_labels: Dict mapping cluster_id -> ClusterLabel
        coords_2d: UMAP 2D coordinates for each trace, shape (n_traces, 2)
        centroid_coords_2d: UMAP 2D coordinates for each centroid, shape (n_clusters, 2)
        batch_run_ids: Dict mapping trace_id -> batch_run_id for linking to summaries
        clustering_params: Parameters used for this clustering run

    Returns:
        List of ClusterData objects emitted
    """
    team = Team.objects.get(id=team_id)
    num_clusters = len(centroids)

    # Fetch trace summaries to get timestamps for efficient linking
    window_start_dt = parse_datetime(window_start)
    window_end_dt = parse_datetime(window_end)
    if window_start_dt is None or window_end_dt is None:
        raise ValueError(f"Invalid datetime format: window_start={window_start}, window_end={window_end}")

    trace_summaries = fetch_trace_summaries(
        team=team,
        trace_ids=trace_ids,
        batch_run_ids=batch_run_ids or {},
        window_start=window_start_dt,
        window_end=window_end_dt,
    )

    # Extract timestamps from summaries
    trace_timestamps: dict[str, str] = {
        trace_id: summary.get("trace_timestamp", "") for trace_id, summary in trace_summaries.items()
    }

    # Build clusters array with centroids and trace distances
    clusters = _build_cluster_data(
        num_clusters=num_clusters,
        labels=labels,
        trace_ids=trace_ids,
        distances_matrix=distances_matrix,
        centroids=centroids,
        cluster_labels=cluster_labels,
        coords_2d=coords_2d,
        centroid_coords_2d=centroid_coords_2d,
        trace_timestamps=trace_timestamps,
    )

    # Build and emit event
    event_uuid = uuid.uuid4()

    properties = {
        "$ai_clustering_run_id": clustering_run_id,
        "$ai_window_start": window_start,
        "$ai_window_end": window_end,
        "$ai_total_traces_analyzed": len(trace_ids),
        "$ai_clusters": [dataclasses.asdict(c) for c in clusters],
    }

    # Add clustering params if provided
    if clustering_params:
        properties["$ai_clustering_params"] = dataclasses.asdict(clustering_params)

    create_event(
        event_uuid=event_uuid,
        event=constants.EVENT_NAME,
        team=team,
        distinct_id=f"trace_clustering_{team_id}",
        properties=properties,
    )

    return clusters


def _build_cluster_data(
    num_clusters: int,
    labels: list[int],
    trace_ids: list[str],
    distances_matrix: np.ndarray,
    centroids: list[list[float]],
    cluster_labels: dict[int, ClusterLabel],
    coords_2d: np.ndarray,
    centroid_coords_2d: np.ndarray,
    trace_timestamps: dict[str, str],
) -> list[ClusterData]:
    """Build cluster data structure with traces and metadata.

    Handles both regular clusters and noise/outlier cluster (cluster_id = -1).
    Noise cluster traces use minimum distance to any centroid.

    Args:
        num_clusters: Number of regular clusters (excludes noise)
        labels: Cluster assignments for each trace (-1 = noise)
        trace_ids: All trace IDs
        distances_matrix: Distance matrix (num_traces x num_clusters)
        centroids: Cluster centroids (only for regular clusters)
        cluster_labels: Dict mapping cluster_id -> ClusterLabel
        coords_2d: UMAP 2D coordinates for each trace, shape (n_traces, 2)
        centroid_coords_2d: UMAP 2D coordinates for each centroid, shape (n_clusters, 2)
        trace_timestamps: Dict mapping trace_id -> timestamp (ISO format)

    Returns:
        List of ClusterData objects (regular clusters first, then noise if present)
    """
    clusters = []
    unique_labels = sorted(set(labels))

    # Process regular clusters first (non-negative IDs)
    for cluster_id in [cid for cid in unique_labels if cid >= 0]:
        cluster_trace_data: list[_TraceDistanceData] = []
        for i, label in enumerate(labels):
            if label == cluster_id:
                trace_id = trace_ids[i]
                cluster_trace_data.append(
                    {
                        "trace_id": trace_id,
                        "distance_to_centroid": float(distances_matrix[i][cluster_id]),
                        "x": float(coords_2d[i][0]),
                        "y": float(coords_2d[i][1]),
                        "timestamp": trace_timestamps.get(trace_id, ""),
                    }
                )

        cluster_trace_data.sort(key=lambda x: x["distance_to_centroid"])

        traces_dict = {
            t["trace_id"]: {
                "distance_to_centroid": t["distance_to_centroid"],
                "rank": rank,
                "x": t["x"],
                "y": t["y"],
                "timestamp": t["timestamp"],
            }
            for rank, t in enumerate(cluster_trace_data)
        }

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
        noise_trace_data: list[_TraceDistanceData] = []
        noise_coords = []

        for i, label in enumerate(labels):
            if label == NOISE_CLUSTER_ID:
                trace_id = trace_ids[i]
                # For noise points, use minimum distance to any centroid
                if distances_matrix.shape[1] > 0:
                    min_distance = float(np.min(distances_matrix[i]))
                else:
                    min_distance = 0.0

                noise_trace_data.append(
                    {
                        "trace_id": trace_id,
                        "distance_to_centroid": min_distance,
                        "x": float(coords_2d[i][0]),
                        "y": float(coords_2d[i][1]),
                        "timestamp": trace_timestamps.get(trace_id, ""),
                    }
                )
                noise_coords.append(coords_2d[i])

        # Sort by distance (most anomalous first - highest min distance)
        noise_trace_data.sort(key=lambda x: x["distance_to_centroid"], reverse=True)

        traces_dict = {
            t["trace_id"]: {
                "distance_to_centroid": t["distance_to_centroid"],
                "rank": rank,
                "x": t["x"],
                "y": t["y"],
                "timestamp": t["timestamp"],
            }
            for rank, t in enumerate(noise_trace_data)
        }

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
            description = "Traces that did not fit into any cluster"

        clusters.append(
            ClusterData(
                cluster_id=NOISE_CLUSTER_ID,
                size=len(traces_dict),
                title=title,
                description=description,
                traces=traces_dict,
                centroid=[],  # No actual centroid for noise cluster
                centroid_x=centroid_x,
                centroid_y=centroid_y,
            )
        )

    return clusters
