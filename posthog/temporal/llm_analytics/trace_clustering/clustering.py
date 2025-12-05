"""Clustering utilities: HDBSCAN and k-means implementations."""

from typing import Literal

import numpy as np
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score
from umap import UMAP

from posthog.temporal.llm_analytics.trace_clustering.models import ClusterRepresentatives, HDBSCANResult, KMeansResult


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

    Raises:
        ValueError: If min_k < 2 or there are fewer samples than min_k
    """
    n_samples = len(embeddings)

    if n_samples == 0:
        raise ValueError("Cannot cluster empty embeddings array")

    if min_k < 2:
        raise ValueError(f"min_k must be at least 2, got {min_k}")

    # silhouette_score requires 1 < n_clusters < n_samples, so cap at n_samples - 1
    effective_max_k = min(max_k, n_samples - 1)

    if n_samples <= min_k:
        raise ValueError(f"Cannot cluster {n_samples} samples with min_k={min_k}. Need at least {min_k + 1} samples.")

    # Ensure we have a valid range
    effective_min_k = min(min_k, effective_max_k)

    best_score = -1.0
    best_kmeans = KMeans(n_clusters=effective_min_k, n_init=10)
    best_kmeans.fit_predict(embeddings)
    best_score = silhouette_score(embeddings, best_kmeans.labels_)

    for k in range(effective_min_k + 1, effective_max_k + 1):
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


def compute_2d_coordinates(
    embeddings: np.ndarray,
    centroids: np.ndarray,
    method: Literal["umap", "pca", "tsne"] = "umap",
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Reduce high-dimensional embeddings and centroids to 2D coordinates for visualization.

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        centroids: Array of centroid vectors, shape (n_clusters, n_features)
        method: Dimensionality reduction method - 'umap', 'pca', or 'tsne'
        n_neighbors: Number of neighbors for UMAP (higher = more global structure)
        min_dist: Minimum distance between points for UMAP (lower = tighter clusters)
        random_state: Random seed for reproducibility

    Returns:
        Tuple of (trace_coords, centroid_coords) where:
        - trace_coords: 2D coordinates array of shape (n_samples, 2)
        - centroid_coords: 2D coordinates array of shape (n_clusters, 2)
    """
    n_samples = len(embeddings)
    n_clusters = len(centroids)

    if n_samples < 2:
        return np.zeros((n_samples, 2)), np.zeros((n_clusters, 2))

    if method == "pca":
        reducer = PCA(n_components=2, random_state=random_state)
        trace_coords = reducer.fit_transform(embeddings)
        if n_clusters == 0:
            centroid_coords = np.zeros((0, 2))
        else:
            centroid_coords = reducer.transform(centroids)

    elif method == "tsne":
        # t-SNE doesn't support transform(), so we need to fit on all points together
        if n_clusters == 0:
            # Adjust perplexity for small samples
            perplexity = min(30, max(5, n_samples // 3))
            tsne = TSNE(n_components=2, perplexity=perplexity, random_state=random_state)
            trace_coords = tsne.fit_transform(embeddings)
            centroid_coords = np.zeros((0, 2))
        else:
            # Combine embeddings and centroids, then split after transform
            combined = np.vstack([embeddings, centroids])
            perplexity = min(30, max(5, len(combined) // 3))
            tsne = TSNE(n_components=2, perplexity=perplexity, random_state=random_state)
            combined_coords = tsne.fit_transform(combined)
            trace_coords = combined_coords[:n_samples]
            centroid_coords = combined_coords[n_samples:]

    else:  # default to umap
        # Adjust n_neighbors if we have fewer samples
        effective_n_neighbors = min(n_neighbors, n_samples - 1)

        reducer = UMAP(
            n_components=2,
            n_neighbors=effective_n_neighbors,
            min_dist=min_dist,
            random_state=random_state,
            metric="euclidean",
            init="random",  # Use random init to avoid spectral layout issues with small samples
        )

        trace_coords = reducer.fit_transform(embeddings)
        if n_clusters == 0:
            centroid_coords = np.zeros((0, 2))
        else:
            centroid_coords = reducer.transform(centroids)

    return trace_coords, centroid_coords


def reduce_dimensions_for_clustering(
    embeddings: np.ndarray,
    n_components: int = 15,
    n_neighbors: int = 15,
    min_dist: float = 0.0,
    random_state: int = 42,
) -> tuple[np.ndarray, UMAP]:
    """
    Reduce high-dimensional embeddings using UMAP for clustering.

    Uses tighter min_dist (0.0) than visualization to better preserve
    cluster structure for HDBSCAN.

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        n_components: Target dimensionality (default 15)
        n_neighbors: Number of neighbors for UMAP
        min_dist: Minimum distance between points (0.0 for clustering)
        random_state: Random seed for reproducibility

    Returns:
        Tuple of (reduced_embeddings, fitted_reducer)
    """
    n_samples = len(embeddings)

    if n_samples < 2:
        return embeddings[:, :n_components] if embeddings.shape[1] >= n_components else embeddings, None

    effective_n_neighbors = min(n_neighbors, n_samples - 1)
    # UMAP's spectral initialization requires n_components < n_samples - 1
    # Use a more conservative limit to avoid scipy eigsh issues
    effective_n_components = min(n_components, max(2, n_samples - 2), embeddings.shape[1])

    reducer = UMAP(
        n_components=effective_n_components,
        n_neighbors=effective_n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
        metric="euclidean",
        init="random",  # Use random init instead of spectral to avoid eigsh issues with small samples
    )

    reduced = reducer.fit_transform(embeddings)
    return reduced, reducer


def reduce_dimensions_pca(
    embeddings: np.ndarray,
    n_components: int = 100,
    random_state: int = 42,
) -> tuple[np.ndarray, PCA]:
    """
    Reduce high-dimensional embeddings using PCA for clustering.

    PCA is faster than UMAP and preserves global structure well.
    Good for high-dimensional embeddings where UMAP may be slow.

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        n_components: Target dimensionality (default 100)
        random_state: Random seed for reproducibility

    Returns:
        Tuple of (reduced_embeddings, fitted_pca)
    """
    n_samples, n_features = embeddings.shape

    if n_samples < 2:
        return embeddings[:, :n_components] if n_features >= n_components else embeddings, None

    # PCA components cannot exceed min(n_samples, n_features)
    effective_n_components = min(n_components, n_samples, n_features)

    reducer = PCA(
        n_components=effective_n_components,
        random_state=random_state,
    )

    reduced = reducer.fit_transform(embeddings)
    return reduced, reducer


def perform_hdbscan_clustering(
    embeddings: np.ndarray,
    min_cluster_size_fraction: float = 0.05,
    min_samples: int = 5,
) -> HDBSCANResult:
    """
    Perform HDBSCAN clustering on embeddings.

    HDBSCAN automatically determines the number of clusters and identifies
    noise points (outliers) that don't fit any cluster.

    Args:
        embeddings: Array of embedding vectors (ideally UMAP-reduced)
        min_cluster_size_fraction: Minimum cluster size as fraction of total samples
        min_samples: Minimum samples in neighborhood for core points

    Returns:
        HDBSCANResult with labels, centroids, probabilities, and noise count
    """
    n_samples = len(embeddings)

    if n_samples == 0:
        raise ValueError("Cannot cluster empty embeddings array")

    # Calculate min_cluster_size from fraction, with minimum of 5
    min_cluster_size = max(5, int(n_samples * min_cluster_size_fraction))

    # Adjust min_samples if needed
    effective_min_samples = min(min_samples, min_cluster_size)

    clusterer = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=effective_min_samples,
        metric="euclidean",
        cluster_selection_method="eom",  # Excess of Mass - good for varying densities
    )

    labels = clusterer.fit_predict(embeddings)
    probabilities = clusterer.probabilities_

    # Compute centroids as mean of cluster members (excluding noise)
    unique_labels = sorted(set(labels) - {-1})  # Exclude noise cluster
    centroids = []

    for cluster_id in unique_labels:
        cluster_mask = labels == cluster_id
        cluster_center = embeddings[cluster_mask].mean(axis=0)
        centroids.append(cluster_center.tolist())

    num_noise_points = int((labels == -1).sum())

    return HDBSCANResult(
        labels=labels.tolist(),
        centroids=centroids,
        probabilities=probabilities.tolist(),
        num_noise_points=num_noise_points,
    )


def select_representatives_by_probability(
    labels: np.ndarray,
    probabilities: np.ndarray,
    trace_ids: list[str],
    n_representatives: int = 5,
) -> ClusterRepresentatives:
    """
    Select representative traces using HDBSCAN membership probabilities.

    For each cluster, selects traces with highest membership probability.
    For noise cluster (-1), selects traces with lowest probability (most anomalous).

    Args:
        labels: Cluster assignments, shape (n_samples,)
        probabilities: Membership probabilities from HDBSCAN
        trace_ids: List of trace IDs corresponding to rows
        n_representatives: Number of representatives per cluster

    Returns:
        ClusterRepresentatives mapping cluster_id to list of representative trace_ids
    """
    representatives: ClusterRepresentatives = {}
    unique_labels = np.unique(labels)

    for cluster_id in unique_labels:
        cluster_mask = labels == cluster_id
        cluster_indices = np.where(cluster_mask)[0]
        cluster_trace_ids = [trace_ids[i] for i in cluster_indices]
        cluster_probs = probabilities[cluster_mask]

        if cluster_id == -1:
            # For noise cluster, select traces with lowest probability (most anomalous)
            sorted_indices = np.argsort(cluster_probs)[:n_representatives]
        else:
            # For regular clusters, select traces with highest probability
            sorted_indices = np.argsort(cluster_probs)[::-1][:n_representatives]

        representative_trace_ids = [cluster_trace_ids[i] for i in sorted_indices]
        representatives[int(cluster_id)] = representative_trace_ids

    return representatives


def calculate_distances_to_cluster_means(
    embeddings: np.ndarray,
    labels: np.ndarray,
    centroids: np.ndarray,
) -> np.ndarray:
    """
    Calculate distances from each trace to all cluster centroids.

    For noise points (label=-1), distances are calculated to all centroids
    to support visualization and analysis.

    Args:
        embeddings: Array of embedding vectors, shape (n_samples, n_features)
        labels: Cluster assignments (can include -1 for noise)
        centroids: Array of centroid vectors, shape (n_clusters, n_features)

    Returns:
        Distance matrix of shape (n_samples, n_clusters)
    """
    if len(centroids) == 0:
        return np.zeros((len(embeddings), 0))

    return np.sqrt(((embeddings[:, np.newaxis, :] - centroids[np.newaxis, :, :]) ** 2).sum(axis=2))
