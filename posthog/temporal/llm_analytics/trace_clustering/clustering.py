"""Clustering utilities: HDBSCAN and k-means implementations."""

import os

# Configure Numba threading layer BEFORE importing UMAP (which uses Numba internally).
# The default "workqueue" threading layer is not thread-safe and crashes when multiple
# Python threads call Numba functions concurrently - which happens when multiple
# Temporal activities run UMAP on the same worker. TBB (Intel Threading Building Blocks)
# is thread-safe and supports concurrent access from multiple Python threads.
# On macOS (local dev), TBB isn't available so we fall back to workqueue - this means
# only one clustering activity should run at a time locally to avoid crashes.
# See: https://numba.readthedocs.io/en/stable/user/threading-layer.html
import sys

if sys.platform == "linux":
    os.environ.setdefault("NUMBA_THREADING_LAYER", "tbb")
# On non-Linux (e.g., macOS dev), leave as default "workqueue" - runs single-threaded

from typing import TYPE_CHECKING, Literal

import numpy as np
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score

from posthog.temporal.llm_analytics.trace_clustering.models import HDBSCANResult, KMeansResult

if TYPE_CHECKING:
    from umap import UMAP


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
        # Lazy import: top-level crashes on prod read-only filesystem (numba JIT cache). Must stay inside function.
        from umap import UMAP

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
) -> tuple[np.ndarray, "UMAP | None"]:
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
    # Lazy import to avoid numba JIT compilation at Django startup
    from umap import UMAP

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

    from posthog.temporal.llm_analytics.trace_clustering.constants import (
        MIN_CLUSTER_SIZE_FRACTION_MAX,
        MIN_CLUSTER_SIZE_FRACTION_MIN,
    )

    if not MIN_CLUSTER_SIZE_FRACTION_MIN <= min_cluster_size_fraction <= MIN_CLUSTER_SIZE_FRACTION_MAX:
        raise ValueError(
            f"min_cluster_size_fraction must be between {MIN_CLUSTER_SIZE_FRACTION_MIN} and {MIN_CLUSTER_SIZE_FRACTION_MAX}"
        )

    # Calculate min_cluster_size from fraction, with minimum of 5 but capped at n_samples
    # HDBSCAN requires min_cluster_size <= n_samples
    min_cluster_size = min(n_samples, max(5, int(n_samples * min_cluster_size_fraction)))

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
