"""
Activity 3 of the video segment clustering workflow:
Clustering video segments using HDBSCAN, with optional noise handling.
"""

import asyncio

import numpy as np
import fast_hdbscan as hdbscan
from sklearn.decomposition import PCA
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.data import fetch_embeddings_by_document_ids
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    ClusteringResult,
    ClusterSegmentsActivityInputs,
    VideoSegment,
)


def reduce_dimensions(embeddings: np.ndarray, n_components: int = constants.PCA_COMPONENTS) -> np.ndarray:
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


def compute_centroid(embeddings: np.ndarray) -> list[float]:
    """Compute the centroid (mean) of a set of embeddings.

    Args:
        embeddings: Array of embedding vectors

    Returns:
        Centroid as a list of floats
    """
    if len(embeddings) == 0:
        return []
    return np.mean(embeddings, axis=0).tolist()


def perform_hdbscan_clustering(
    segments: list[VideoSegment],
    min_cluster_size: int = constants.MIN_CLUSTER_SIZE,
    min_samples: int = constants.MIN_SAMPLES,
    cluster_selection_method: str = constants.CLUSTER_SELECTION_METHOD,
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
    reduced_embeddings = reduce_dimensions(embeddings)

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
        centroid = compute_centroid(cluster_embeddings)

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


def create_single_segment_clusters(
    noise_segment_ids: list[str],
    segments: list[VideoSegment],
    starting_cluster_id: int,
) -> list[Cluster]:
    """Create individual clusters for noise segments (one segment per cluster).

    Used for high-impact noise segments that should become individual Tasks
    even without clustering with other segments.

    Args:
        noise_segment_ids: List of document IDs for noise segments
        segments: All segments (to look up embeddings)
        starting_cluster_id: First cluster ID to use (to avoid conflicts)

    Returns:
        List of single-segment Clusters
    """
    segment_lookup = {s.document_id: s for s in segments}
    clusters: list[Cluster] = []

    for i, doc_id in enumerate(noise_segment_ids):
        segment = segment_lookup.get(doc_id)
        if not segment:
            continue

        cluster = Cluster(
            cluster_id=starting_cluster_id + i,
            segment_ids=[doc_id],
            centroid=segment.embedding,  # Single segment = its embedding is the centroid
            size=1,
        )
        clusters.append(cluster)

    return clusters


def _perform_clustering(
    segments: list[VideoSegment],
    create_single_segment_clusters_for_noise: bool,
) -> ClusteringResult:
    """Run HDBSCAN clustering and optionally handle noise. CPU-bound."""
    result = perform_hdbscan_clustering(segments)

    if create_single_segment_clusters_for_noise and result.noise_segment_ids:
        max_cluster_id = max((c.cluster_id for c in result.clusters), default=-1)

        noise_clusters = create_single_segment_clusters(
            noise_segment_ids=result.noise_segment_ids,
            segments=segments,
            starting_cluster_id=max_cluster_id + 1,
        )

        all_clusters = list(result.clusters) + noise_clusters
        segment_to_cluster = dict(result.segment_to_cluster)
        for cluster in noise_clusters:
            for doc_id in cluster.segment_ids:
                segment_to_cluster[doc_id] = cluster.cluster_id

        return ClusteringResult(
            clusters=all_clusters,
            noise_segment_ids=[],
            labels=result.labels,
            segment_to_cluster=segment_to_cluster,
        )

    return result


@activity.defn
async def cluster_segments_activity(inputs: ClusterSegmentsActivityInputs) -> ClusteringResult:
    """Cluster video segments using HDBSCAN.

    Fetches embeddings from ClickHouse, then applies PCA dimensionality reduction
    and HDBSCAN clustering. Returns clusters with centroids computed from original embeddings.

    If create_single_segment_clusters_for_noise is True, noise segments are converted to
    single-segment clusters so they can become individual Tasks.
    """
    team = await Team.objects.aget(id=inputs.team_id)
    segments = await fetch_embeddings_by_document_ids(team, inputs.document_ids)

    return await asyncio.to_thread(
        _perform_clustering,
        segments,
        inputs.create_single_segment_clusters_for_noise,
    )
