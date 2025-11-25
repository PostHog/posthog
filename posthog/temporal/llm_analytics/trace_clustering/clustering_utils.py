"""Clustering utilities: k-means implementation and optimal k selection."""

import logging

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from posthog.temporal.llm_analytics.trace_clustering.models import ClusterRepresentatives, KMeansResult

logger = logging.getLogger(__name__)


def perform_kmeans_with_optimal_k(
    embeddings: np.ndarray,
    min_k: int,
    max_k: int,
) -> KMeansResult:
    """
    Determine optimal k using silhouette score and return the clustering results.

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        min_k: Minimum number of clusters to test
        max_k: Maximum number of clusters to test

    Returns:
        KMeansResult with labels and centroids
    """
    best_score = -1.0
    best_kmeans = None

    for k in range(min_k, max_k + 1):
        kmeans = KMeans(n_clusters=k, n_init=10)
        kmeans.fit_predict(embeddings)
        score = silhouette_score(embeddings, kmeans.labels_)

        if score > best_score:
            best_score = score
            best_kmeans = kmeans

    return KMeansResult(
        labels=best_kmeans.labels_.tolist(),
        centroids=best_kmeans.cluster_centers_.tolist(),
    )


def calculate_trace_distances(
    embeddings: np.ndarray,
    centroids: np.ndarray,
) -> np.ndarray:
    """
    Calculate Euclidean distances from each trace embedding to all centroids.

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        centroids: Array of centroid vectors, shape (n_clusters, n_features)

    Returns:
        Distance matrix of shape (n_samples, n_clusters)
    """
    # Shape: (n_samples, n_clusters)
    # broadcasting: (n_samples, 1, n_features) - (1, n_clusters, n_features)
    return np.sqrt(((embeddings[:, np.newaxis, :] - centroids[np.newaxis, :, :]) ** 2).sum(axis=2))


def select_representatives_from_distances(
    labels: np.ndarray,
    distances_matrix: np.ndarray,
    trace_ids: list[str],
    n_closest: int = 5,
) -> "ClusterRepresentatives":
    """
    Select representative traces using pre-computed distances.

    For each cluster, selects n_closest traces closest to the cluster centroid
    using distances that have already been calculated.

    Args:
        labels: Cluster assignments, shape (n_samples,)
        distances_matrix: Pre-computed distances, shape (n_samples, k)
        trace_ids: List of trace IDs corresponding to rows
        n_closest: Number of closest traces to select per cluster

    Returns:
        ClusterRepresentatives mapping cluster_id to list of representative trace_ids
    """
    representatives: ClusterRepresentatives = {}
    unique_labels = np.unique(labels)

    for cluster_id in unique_labels:
        cluster_mask = labels == cluster_id
        cluster_indices = np.where(cluster_mask)[0]
        cluster_trace_ids = [trace_ids[i] for i in cluster_indices]

        # Get distances to this cluster's centroid (column cluster_id)
        distances = distances_matrix[cluster_mask, cluster_id]

        # Select closest traces
        closest_local_indices = np.argsort(distances)[:n_closest]
        closest_trace_ids = [cluster_trace_ids[i] for i in closest_local_indices]

        representatives[int(cluster_id)] = closest_trace_ids

    return representatives
