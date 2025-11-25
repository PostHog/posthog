"""Clustering utilities: k-means implementation and optimal k selection."""

import logging

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from posthog.temporal.llm_analytics.trace_clustering.constants import MIN_TRACES_FOR_CLUSTERING

logger = logging.getLogger(__name__)


def determine_optimal_k(
    embeddings: np.ndarray,
    min_k: int,
    max_k: int,
    random_state: int = 42,
) -> tuple[int, dict[int, float]]:
    """
    Determine optimal number of clusters using silhouette score.

    Tests each k value from min_k to max_k and returns the k with
    the highest silhouette score.

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        min_k: Minimum number of clusters to test
        max_k: Maximum number of clusters to test
        random_state: Random seed for reproducibility

    Returns:
        Tuple of (optimal_k, scores_dict)
        - optimal_k: The k value with highest silhouette score
        - scores_dict: Dictionary mapping k to silhouette score

    Raises:
        ValueError: If insufficient data for clustering
    """
    n_samples = len(embeddings)

    # Validate we have enough samples
    if n_samples < MIN_TRACES_FOR_CLUSTERING:
        raise ValueError(f"Insufficient traces for clustering: {n_samples} < {MIN_TRACES_FOR_CLUSTERING}")

    # Adjust max_k if we don't have enough samples
    # Need at least k+1 samples for valid silhouette score
    max_k = min(max_k, n_samples - 1)

    if max_k < min_k:
        raise ValueError(f"Not enough samples ({n_samples}) to test k range [{min_k}, {max_k}]")

    scores = {}
    best_k = min_k
    best_score = -1.0

    for k in range(min_k, max_k + 1):
        kmeans = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = kmeans.fit_predict(embeddings)

        score = silhouette_score(embeddings, labels)
        scores[k] = score

        if score > best_score:
            best_score = score
            best_k = k

    return best_k, scores


def perform_kmeans_clustering(
    embeddings: np.ndarray,
    k: int,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Perform k-means clustering on embeddings.

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        k: Number of clusters
        random_state: Random seed for reproducibility

    Returns:
        Tuple of (labels, centroids, inertia)
        - labels: Cluster assignment for each sample, shape (n_samples,)
        - centroids: Cluster centroids, shape (k, n_features)
        - inertia: Sum of squared distances to nearest centroid
    """

    kmeans = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    labels = kmeans.fit_predict(embeddings)
    centroids = kmeans.cluster_centers_
    inertia = kmeans.inertia_

    return labels, centroids, inertia


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
) -> dict[int, list[str]]:
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
        Dictionary mapping cluster_id to list of representative trace_ids
    """
    representatives = {}
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
