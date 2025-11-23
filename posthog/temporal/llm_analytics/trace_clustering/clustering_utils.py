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

    logger.info(f"Testing k values from {min_k} to {max_k} on {n_samples} samples")

    for k in range(min_k, max_k + 1):
        logger.info(f"Testing k={k}")

        # Run k-means
        kmeans = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = kmeans.fit_predict(embeddings)

        # Calculate silhouette score
        score = silhouette_score(embeddings, labels)
        scores[k] = score

        logger.info(f"k={k}: silhouette_score={score:.4f}")

        # Track best k
        if score > best_score:
            best_score = score
            best_k = k

    logger.info(f"Optimal k determined: {best_k} (score={best_score:.4f})")

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
    logger.info(f"Performing k-means clustering with k={k} on {len(embeddings)} samples")

    kmeans = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    labels = kmeans.fit_predict(embeddings)
    centroids = kmeans.cluster_centers_
    inertia = kmeans.inertia_

    logger.info(f"Clustering complete: inertia={inertia:.2f}")

    return labels, centroids, inertia


def select_cluster_representatives(
    embeddings: np.ndarray,
    labels: np.ndarray,
    centroids: np.ndarray,
    trace_ids: list[str],
    n_closest: int = 5,
    n_random: int = 2,
    random_state: int = 42,
) -> dict[int, list[str]]:
    """
    Select representative traces for each cluster.

    For each cluster, selects:
    - n_closest traces closest to the cluster centroid (most representative)
    - n_random random traces (for diversity)

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        labels: Cluster assignments, shape (n_samples,)
        centroids: Cluster centroids, shape (k, n_features)
        trace_ids: List of trace IDs corresponding to embeddings
        n_closest: Number of closest traces to select per cluster
        n_random: Number of random traces to select per cluster
        random_state: Random seed for reproducibility

    Returns:
        Dictionary mapping cluster_id to list of representative trace_ids
    """
    np.random.seed(random_state)
    representatives = {}

    unique_labels = np.unique(labels)

    for cluster_id in unique_labels:
        # Get indices of traces in this cluster
        cluster_mask = labels == cluster_id
        cluster_indices = np.where(cluster_mask)[0]
        cluster_embeddings = embeddings[cluster_mask]
        cluster_trace_ids = [trace_ids[i] for i in cluster_indices]

        # Calculate distances to centroid
        centroid = centroids[cluster_id]
        distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)

        # Get n_closest closest traces
        closest_indices = np.argsort(distances)[:n_closest]
        closest_trace_ids = [cluster_trace_ids[i] for i in closest_indices]

        # Get n_random random traces (excluding the closest ones)
        remaining_indices = [i for i in range(len(cluster_trace_ids)) if i not in closest_indices]
        if len(remaining_indices) >= n_random:
            random_indices = np.random.choice(remaining_indices, size=n_random, replace=False)
            random_trace_ids = [cluster_trace_ids[i] for i in random_indices]
        else:
            # If not enough remaining, just take what we have
            random_trace_ids = [cluster_trace_ids[i] for i in remaining_indices]

        # Combine closest and random
        representatives[int(cluster_id)] = closest_trace_ids + random_trace_ids

        logger.info(
            f"Cluster {cluster_id}: selected {len(closest_trace_ids)} closest + {len(random_trace_ids)} random "
            f"= {len(representatives[int(cluster_id)])} representatives"
        )

    return representatives
