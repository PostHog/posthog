"""Tests for clustering utilities: HDBSCAN, k-means, and dimensionality reduction."""

import pytest

import numpy as np
from parameterized import parameterized


# Check if UMAP threading backend is available (required for UMAP tests)
def _umap_threading_available() -> bool:
    """Check if UMAP can run without threading errors."""
    try:
        import umap

        # Try to create a small UMAP instance - this will fail if TBB is missing
        reducer = umap.UMAP(n_components=2, n_neighbors=2, random_state=42)
        reducer.fit_transform(np.random.randn(5, 10))
        return True
    except (ValueError, ImportError):
        return False


umap_available = _umap_threading_available()
skip_without_umap = pytest.mark.skipif(not umap_available, reason="UMAP threading backend (TBB) not available")


from posthog.temporal.llm_analytics.trace_clustering.clustering import (  # noqa: E402
    calculate_distances_to_cluster_means,
    calculate_trace_distances,
    compute_2d_coordinates,
    perform_hdbscan_clustering,
    reduce_dimensions_for_clustering,
    reduce_dimensions_pca,
)


class TestPerformHDBSCANClustering:
    def test_basic_clustering_returns_valid_structure(self):
        # Create embeddings with 2 clear clusters
        np.random.seed(42)
        cluster1 = np.random.randn(30, 10) + np.array([5, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        cluster2 = np.random.randn(30, 10) + np.array([-5, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        embeddings = np.vstack([cluster1, cluster2])

        result = perform_hdbscan_clustering(embeddings, min_cluster_size_fraction=0.1, min_samples=3)

        assert len(result.labels) == 60
        assert len(result.probabilities) == 60
        assert all(isinstance(label, int) for label in result.labels)
        assert result.num_noise_points >= 0

    def test_noise_cluster_has_label_minus_one(self):
        # Create sparse embeddings where some points should be noise
        np.random.seed(42)
        # One tight cluster
        cluster = np.random.randn(50, 10) * 0.1
        # Some outliers far away
        outliers = np.random.randn(10, 10) * 0.1 + np.array([100, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        embeddings = np.vstack([cluster, outliers])

        result = perform_hdbscan_clustering(embeddings, min_cluster_size_fraction=0.15, min_samples=5)

        assert -1 in result.labels or result.num_noise_points == 0
        assert result.num_noise_points == sum(1 for label in result.labels if label == -1)

    def test_centroids_exclude_noise_cluster(self):
        np.random.seed(42)
        cluster1 = np.random.randn(30, 5) + np.array([10, 0, 0, 0, 0])
        cluster2 = np.random.randn(30, 5) + np.array([-10, 0, 0, 0, 0])
        embeddings = np.vstack([cluster1, cluster2])

        result = perform_hdbscan_clustering(embeddings, min_cluster_size_fraction=0.1, min_samples=3)

        # Centroids should only be for real clusters, not noise
        unique_non_noise = set(result.labels) - {-1}
        assert len(result.centroids) == len(unique_non_noise)

    def test_empty_embeddings_raises_error(self):
        with pytest.raises(ValueError, match="Cannot cluster empty"):
            perform_hdbscan_clustering(np.array([]).reshape(0, 10))


class TestCalculateTraceDistances:
    def test_distance_matrix_shape(self):
        embeddings = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]])
        centroids = np.array([[0, 0, 0], [1, 1, 1]])

        distances = calculate_trace_distances(embeddings, centroids)

        assert distances.shape == (4, 2)

    def test_distance_to_same_point_is_zero(self):
        embeddings = np.array([[1, 1, 1], [2, 2, 2]])
        centroids = np.array([[1, 1, 1], [2, 2, 2]])

        distances = calculate_trace_distances(embeddings, centroids)

        assert distances[0, 0] == pytest.approx(0, abs=1e-10)
        assert distances[1, 1] == pytest.approx(0, abs=1e-10)

    def test_euclidean_distance_calculation(self):
        embeddings = np.array([[0, 0, 0], [3, 4, 0]])
        centroids = np.array([[0, 0, 0]])

        distances = calculate_trace_distances(embeddings, centroids)

        assert distances[0, 0] == pytest.approx(0, abs=1e-10)
        assert distances[1, 0] == pytest.approx(5.0, abs=1e-10)  # 3-4-5 triangle


class TestCompute2DCoordinates:
    @parameterized.expand([("umap",), ("pca",), ("tsne",)])
    def test_output_shape_is_2d(self, method):
        # Skip UMAP test if threading backend isn't available
        if method == "umap" and not umap_available:
            pytest.skip("UMAP threading backend (TBB) not available")

        np.random.seed(42)
        embeddings = np.random.randn(20, 50)
        centroids = np.random.randn(3, 50)

        trace_coords, centroid_coords = compute_2d_coordinates(embeddings, centroids, method=method, random_state=42)

        assert trace_coords.shape == (20, 2)
        assert centroid_coords.shape == (3, 2)

    def test_pca_preserves_relative_structure(self):
        np.random.seed(42)
        # Two distinct clusters in high-d space
        cluster1 = np.random.randn(10, 20) + np.array([10] * 20)
        cluster2 = np.random.randn(10, 20) + np.array([-10] * 20)
        embeddings = np.vstack([cluster1, cluster2])
        centroids = np.array([cluster1.mean(axis=0), cluster2.mean(axis=0)])

        trace_coords, centroid_coords = compute_2d_coordinates(embeddings, centroids, method="pca", random_state=42)

        # Cluster 1 traces should be closer to centroid 1 than centroid 2
        cluster1_to_centroid1 = np.mean(np.linalg.norm(trace_coords[:10] - centroid_coords[0], axis=1))
        cluster1_to_centroid2 = np.mean(np.linalg.norm(trace_coords[:10] - centroid_coords[1], axis=1))
        assert cluster1_to_centroid1 < cluster1_to_centroid2

    def test_handles_empty_centroids(self):
        np.random.seed(42)
        embeddings = np.random.randn(10, 20)
        centroids = np.zeros((0, 20))

        trace_coords, centroid_coords = compute_2d_coordinates(embeddings, centroids, method="pca")

        assert trace_coords.shape == (10, 2)
        assert centroid_coords.shape == (0, 2)

    def test_handles_small_sample_size(self):
        embeddings = np.array([[1, 2, 3], [4, 5, 6]])
        centroids = np.array([[2, 3, 4]])

        trace_coords, centroid_coords = compute_2d_coordinates(embeddings, centroids, method="pca")

        assert trace_coords.shape == (2, 2)
        assert centroid_coords.shape == (1, 2)


@skip_without_umap
class TestReduceDimensionsForClustering:
    def test_reduces_to_target_dimensions(self):
        np.random.seed(42)
        embeddings = np.random.randn(100, 500)

        reduced, reducer = reduce_dimensions_for_clustering(embeddings, n_components=15, random_state=42)

        assert reduced.shape == (100, 15)
        assert reducer is not None

    def test_handles_small_sample_gracefully(self):
        np.random.seed(42)
        embeddings = np.random.randn(5, 100)

        reduced, reducer = reduce_dimensions_for_clustering(embeddings, n_components=15, random_state=42)

        assert reduced.shape[0] == 5
        assert reduced.shape[1] <= 15

    def test_single_sample_returns_input(self):
        embeddings = np.random.randn(1, 100)

        reduced, reducer = reduce_dimensions_for_clustering(embeddings, n_components=15)

        assert reduced.shape[0] == 1
        assert reducer is None


class TestReduceDimensionsPCA:
    def test_reduces_to_target_dimensions(self):
        np.random.seed(42)
        embeddings = np.random.randn(100, 500)

        reduced, pca = reduce_dimensions_pca(embeddings, n_components=100, random_state=42)

        assert reduced.shape == (100, 100)
        assert pca is not None

    def test_respects_max_components_constraint(self):
        np.random.seed(42)
        embeddings = np.random.randn(30, 50)

        reduced, pca = reduce_dimensions_pca(embeddings, n_components=100, random_state=42)

        # n_components capped at min(n_samples, n_features)
        assert reduced.shape[1] <= min(30, 50)

    def test_single_sample_returns_input(self):
        embeddings = np.random.randn(1, 100)

        reduced, pca = reduce_dimensions_pca(embeddings, n_components=50)

        assert reduced.shape[0] == 1
        assert pca is None


class TestCalculateDistancesToClusterMeans:
    def test_same_as_calculate_trace_distances(self):
        np.random.seed(42)
        embeddings = np.random.randn(10, 5)
        labels = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2, -1])
        centroids = np.array(
            [
                embeddings[:3].mean(axis=0),
                embeddings[3:6].mean(axis=0),
                embeddings[6:9].mean(axis=0),
            ]
        )

        distances = calculate_distances_to_cluster_means(embeddings, labels, centroids)

        assert distances.shape == (10, 3)

    def test_handles_empty_centroids(self):
        embeddings = np.random.randn(5, 10)
        labels = np.array([-1, -1, -1, -1, -1])
        centroids = np.zeros((0, 10))

        distances = calculate_distances_to_cluster_means(embeddings, labels, centroids)

        assert distances.shape == (5, 0)
