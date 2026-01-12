"""Clustering utilities: HDBSCAN with PCA dimensionality reduction."""

import numpy as np
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_distances

from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    ClusteringResult,
    MatchingResult,
    TaskMatch,
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
    try:
        import hdbscan
    except ImportError:
        raise ImportError("hdbscan package is required for clustering. Install with: pip install hdbscan")

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

    # Perform HDBSCAN clustering with relaxed parameters
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",  # Use euclidean on PCA-reduced space
        cluster_selection_method=cluster_selection_method,
        cluster_selection_epsilon=cluster_selection_epsilon,
        prediction_data=True,
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


def match_clusters_to_existing_tasks(
    clusters: list[Cluster],
    existing_task_centroids: dict[str, list[float]],
    match_threshold: float = constants.TASK_MATCH_THRESHOLD,
) -> MatchingResult:
    """Match new clusters to existing Tasks based on centroid similarity.

    Args:
        clusters: List of new clusters from HDBSCAN
        existing_task_centroids: Dict mapping task_id -> centroid embedding
        match_threshold: Maximum cosine distance to consider a match

    Returns:
        MatchingResult with new clusters and matched clusters
    """
    if not existing_task_centroids:
        # No existing tasks, all clusters are new
        return MatchingResult(
            new_clusters=clusters,
            matched_clusters=[],
        )

    new_clusters: list[Cluster] = []
    matched_clusters: list[TaskMatch] = []

    # Convert task centroids to arrays for efficient comparison
    task_ids = list(existing_task_centroids.keys())
    task_centroids = np.array(list(existing_task_centroids.values()))

    for cluster in clusters:
        cluster_centroid = np.array(cluster.centroid).reshape(1, -1)

        # Calculate cosine distances to all task centroids
        distances = cosine_distances(cluster_centroid, task_centroids)[0]

        # Find best match
        min_idx = np.argmin(distances)
        min_distance = distances[min_idx]

        if min_distance < match_threshold:
            # Found a match
            matched_clusters.append(
                TaskMatch(
                    cluster_id=cluster.cluster_id,
                    task_id=task_ids[min_idx],
                    distance=float(min_distance),
                )
            )
        else:
            # No match, this is a new cluster
            new_clusters.append(cluster)

    return MatchingResult(
        new_clusters=new_clusters,
        matched_clusters=matched_clusters,
    )


def update_task_centroid(
    existing_centroid: list[float],
    existing_count: int,
    new_embeddings: np.ndarray,
) -> list[float]:
    """Update a task's centroid with new segment embeddings using weighted average.

    Args:
        existing_centroid: Current centroid embedding
        existing_count: Number of segments that contributed to existing centroid
        new_embeddings: Array of new segment embeddings

    Returns:
        Updated centroid as list of floats
    """
    if len(new_embeddings) == 0:
        return existing_centroid

    new_count = len(new_embeddings)
    new_centroid = np.mean(new_embeddings, axis=0)

    # Weighted average
    total_count = existing_count + new_count
    updated_centroid = (np.array(existing_centroid) * existing_count + new_centroid * new_count) / total_count

    return updated_centroid.tolist()


def calculate_cosine_distance(embedding1: list[float], embedding2: list[float]) -> float:
    """Calculate cosine distance between two embeddings.

    Args:
        embedding1: First embedding vector
        embedding2: Second embedding vector

    Returns:
        Cosine distance (0 = identical, 2 = opposite)
    """
    vec1 = np.array(embedding1).reshape(1, -1)
    vec2 = np.array(embedding2).reshape(1, -1)
    return float(cosine_distances(vec1, vec2)[0, 0])


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
