"""
Activity 3 of the video segment clustering workflow:
Clustering video segments using HDBSCAN, with noise handling.
"""

import json
import asyncio
from typing import Literal

import numpy as np
import fast_hdbscan as hdbscan
from sklearn.decomposition import PCA
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    ClusteringResult,
    ClusterSegmentsActivityInputs,
    VideoSegment,
)
from posthog.temporal.common.logger import get_logger

from ..data import fetch_video_segment_embedding_rows

logger = get_logger(__name__)


@activity.defn
async def cluster_segments_activity(inputs: ClusterSegmentsActivityInputs) -> ClusteringResult:
    """Cluster video segments using HDBSCAN.

    Fetches embeddings from ClickHouse, then applies PCA dimensionality reduction
    and HDBSCAN clustering. Returns clusters with centroids computed from original embeddings.

    If create_single_segment_clusters_for_noise is True (default), noise segments are converted to
    single-segment clusters so they can become individual Tasks (mostly for teams with lower usage).

    Why HDBSCAN? I'm not an expert, so I'm using Claude as my PhD-level advisor on this (can recommend):
    - Crucially, doesn't require specifying cluster count upfront, unlike K-means
    - Naturally identifies noise: segments that don't belong to any cluster
    - Discovers clusters of varying densities and shapes
    The downsides of HDBSCAN:
    - Slower than K-means, especially on large sets (but fast_hdbscan should be a, well, fast library)
    - Sensitive to min_cluster_size/min_samples parameters
    - Struggles with high-dimensional data (hence dimensionality reduction with PCA first)

    Glossary:
    - PCA: Principal Component Analysis
    - HDBSCAN: Hierarchical Density-Based Spatial Clustering of Applications with Noise
    """
    team = await Team.objects.aget(id=inputs.team_id)
    # We fetch segments here instead of passing via Temporal, to avoid large Temporal payloads (each embedding is 3 KB)
    segments = await _fetch_embeddings_by_document_ids(team, inputs.document_ids)

    # Run in to_thread as clustering is CPU-bound
    return await asyncio.to_thread(
        _perform_clustering,
        segments,
        inputs.create_single_segment_clusters_for_noise,
    )


async def _fetch_embeddings_by_document_ids(
    team: Team,
    document_ids: list[str],
) -> list[VideoSegment]:
    if not document_ids:
        return []

    rows = await fetch_video_segment_embedding_rows(team, document_ids)
    segments: list[VideoSegment] = []

    for row in rows:
        document_id, content, embedding, metadata_str, _timestamp_of_embedding = row
        try:
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
        except (json.JSONDecodeError, TypeError):
            # Being defensive to avoid a poison pill kind of situation
            logger.exception(f"Failed to parse metadata for document_id: {document_id}", metadata_str=metadata_str)
            continue
        session_id = metadata.get("session_id")
        start_time = metadata.get("start_time")
        end_time = metadata.get("end_time")
        distinct_id = metadata.get("distinct_id")
        session_start_time = metadata.get("session_start_time")
        session_end_time = metadata.get("session_end_time")
        session_duration = metadata.get("session_duration")
        session_active_seconds = metadata.get("session_active_seconds")
        if (
            not session_id
            or not start_time
            or not end_time
            or not distinct_id
            or not session_start_time
            or not session_end_time
            or not session_duration
            or not session_active_seconds
        ):
            logger.error(f"Missing required metadata for document_id: {document_id}", metadata=metadata)
            continue
        segments.append(
            VideoSegment(
                document_id=document_id,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
                session_start_time=session_start_time,
                session_end_time=session_end_time,
                session_duration=session_duration,
                session_active_seconds=session_active_seconds,
                distinct_id=distinct_id,
                content=content,
                embedding=embedding,
            )
        )

    return segments


def _perform_clustering(
    segments: list[VideoSegment],
    create_single_segment_clusters_for_noise: bool,
) -> ClusteringResult:
    """Run HDBSCAN clustering and handle noise. CPU-bound."""
    result = _perform_hdbscan_clustering(segments)

    if create_single_segment_clusters_for_noise and result.noise_segment_ids:
        # Handle noise segments by creating single-segment clusters
        max_cluster_id = max((c.cluster_id for c in result.clusters), default=-1)
        noise_clusters = _create_single_segment_clusters(
            noise_segment_ids=result.noise_segment_ids,
            all_segments=segments,
            cluster_id_offset=max_cluster_id + 1,
        )
        # Update result in place
        result.clusters += noise_clusters
        result.noise_segment_ids = []
        for cluster in noise_clusters:
            for doc_id in cluster.segment_ids:
                result.segment_to_cluster[doc_id] = cluster.cluster_id

    return result


def _perform_hdbscan_clustering(
    segments: list[VideoSegment],
    min_cluster_size: int = constants.MIN_CLUSTER_SIZE,
    min_samples: int = constants.MIN_SAMPLES,
    cluster_selection_method: Literal["leaf", "eom"] = constants.CLUSTER_SELECTION_METHOD,
    cluster_selection_epsilon: float = constants.CLUSTER_SELECTION_EPSILON,
) -> ClusteringResult:
    """Cluster video segments using HDBSCAN algorithm.

    HDBSCAN is density-based and doesn't require specifying the number of clusters.
    It naturally handles noise (segments that don't fit any cluster).

    Uses relaxed parameters to work well with small datasets:
    - min_cluster_size=2: allows pairs of similar segments to form clusters
    - min_samples=1: less conservative, allows more clusters
    - cluster_selection_method='leaf': produces more granular clusters

    Args:
        segments: List of video segments with embeddings
        min_cluster_size: Minimum number of segments to form a cluster
        min_samples: Minimum samples for core points
        cluster_selection_method: 'leaf' for granular or 'eom' for broader clusters
        cluster_selection_epsilon: Distance threshold for cluster membership

    Returns:
        ClusteringResult with clusters, noise segments, and mappings
    """
    if len(segments) == 0:
        return ClusteringResult(
            clusters=[],
            noise_segment_ids=[],
            labels=[],
            segment_to_cluster={},
        )

    # Extract embeddings (full 3072 dimensions)
    embeddings = np.array([s.embedding for s in segments])
    document_ids = [s.document_id for s in segments]

    # Reduce dimensions for clustering efficiency
    reduced_embeddings = _reduce_dimensions(embeddings)

    # Perform HDBSCAN clustering with relaxed parameters (note: fast_hdbscan is Euclidean-only, no cosine due to perf)
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method=cluster_selection_method,
        cluster_selection_epsilon=cluster_selection_epsilon,
    )

    labels = clusterer.fit_predict(reduced_embeddings)

    # Build clusters using ORIGINAL embeddings for centroids (not PCA-reduced)
    clusters: list[Cluster] = []
    noise_segment_ids: list[str] = []
    segment_to_cluster: dict[str, int] = {}

    unique_labels = set(labels)
    for label in unique_labels:
        if label == -1:
            # Noise points
            noise_indices = np.where(labels == label)[0]
            noise_segment_ids.extend([document_ids[i] for i in noise_indices])
            continue

        # Get segments in this cluster
        cluster_indices = np.where(labels == label)[0]
        cluster_segment_ids = [document_ids[i] for i in cluster_indices]

        # Compute centroid from ORIGINAL embeddings (not reduced)
        cluster_embeddings = embeddings[cluster_indices]
        centroid = np.mean(cluster_embeddings, axis=0).tolist() if len(cluster_embeddings) else []

        cluster = Cluster(
            cluster_id=int(label),
            segment_ids=cluster_segment_ids,
            centroid=centroid,
            size=len(cluster_segment_ids),
        )
        clusters.append(cluster)

        # Update mapping
        for seg_id in cluster_segment_ids:
            segment_to_cluster[seg_id] = int(label)

    return ClusteringResult(
        clusters=clusters,
        noise_segment_ids=noise_segment_ids,
        labels=labels.tolist(),
        segment_to_cluster=segment_to_cluster,
    )


def _reduce_dimensions(
    embeddings: np.ndarray, n_components: int = constants.TARGET_DIMENSIONALITY_FOR_CLUSTERING
) -> np.ndarray:
    """Reduce embedding dimensions using PCA for efficient clustering.

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        n_components: Target number of dimensions

    Returns:
        Reduced embeddings array, shape (n_samples, n_components)
    """
    if embeddings.shape[0] == 0:
        return embeddings
    # Don't reduce if already smaller than target
    if embeddings.shape[1] <= n_components:
        return embeddings
    # Cap components at number of samples (PCA requirement)
    effective_components = min(n_components, embeddings.shape[0])
    pca = PCA(n_components=effective_components)
    return pca.fit_transform(embeddings)


def _create_single_segment_clusters(
    *,
    noise_segment_ids: list[str],
    all_segments: list[VideoSegment],
    cluster_id_offset: int,
) -> list[Cluster]:
    segment_lookup = {s.document_id: s for s in all_segments}
    new_clusters: list[Cluster] = []
    for i, doc_id in enumerate(noise_segment_ids):
        segment = segment_lookup.get(doc_id)
        if not segment:
            continue
        new_clusters.append(
            Cluster(
                cluster_id=cluster_id_offset + i,
                segment_ids=[doc_id],
                centroid=segment.embedding,  # Single segment = its embedding is the centroid
                size=1,
            )
        )
    return new_clusters
