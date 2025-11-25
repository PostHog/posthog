"""Tests for trace clustering workflow."""

import pytest

import numpy as np

from posthog.temporal.llm_analytics.trace_clustering.clustering_utils import (
    calculate_trace_distances,
    perform_kmeans_with_optimal_k,
    select_representatives_from_distances,
)
from posthog.temporal.llm_analytics.trace_clustering.models import ClusteringInputs


@pytest.fixture
def mock_team(db):
    """Create a test team."""
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(
        organization=organization,
        name="Test Team",
    )
    return team


@pytest.fixture
def sample_embeddings():
    """Generate sample embeddings for testing.

    Returns list of dicts with trace_id and embedding keys.
    """
    np.random.seed(42)
    embeddings = []

    # Create 100 embeddings in 3 clusters
    for i in range(30):
        # Cluster 0: around [1, 1, 1, ...]
        embedding = np.random.normal(1.0, 0.1, 384).tolist()
        embeddings.append({"trace_id": f"trace_0_{i}", "embedding": embedding})

    for i in range(30):
        # Cluster 1: around [5, 5, 5, ...]
        embedding = np.random.normal(5.0, 0.1, 384).tolist()
        embeddings.append({"trace_id": f"trace_1_{i}", "embedding": embedding})

    for i in range(40):
        # Cluster 2: around [10, 10, 10, ...]
        embedding = np.random.normal(10.0, 0.1, 384).tolist()
        embeddings.append({"trace_id": f"trace_2_{i}", "embedding": embedding})

    return embeddings


class TestClusteringUtils:
    """Tests for clustering utility functions."""

    def test_perform_kmeans_with_optimal_k_success(self, sample_embeddings):
        """Test optimal k determination and clustering with valid data."""
        embeddings_array = np.array([e["embedding"] for e in sample_embeddings])

        result = perform_kmeans_with_optimal_k(embeddings_array, min_k=2, max_k=5)

        num_clusters = len(result.centroids)
        assert 2 <= num_clusters <= 5
        assert len(result.labels) == len(sample_embeddings)
        # Should pick k=3 since we generated 3 clusters
        assert num_clusters == 3

    def test_perform_kmeans_with_optimal_k_returns_correct_structure(self, sample_embeddings):
        """Test that perform_kmeans_with_optimal_k returns correct KMeansResult structure."""
        embeddings_array = np.array([e["embedding"] for e in sample_embeddings])

        result = perform_kmeans_with_optimal_k(embeddings_array, min_k=2, max_k=5)

        assert isinstance(result.labels, list)
        assert isinstance(result.centroids, list)
        assert len(result.labels) == len(sample_embeddings)
        assert all(isinstance(label, int) for label in result.labels)
        assert all(isinstance(centroid, list) for centroid in result.centroids)

    def test_select_representatives_from_distances(self, sample_embeddings):
        """Test representative selection using pre-computed distances."""
        embeddings_array = np.array([e["embedding"] for e in sample_embeddings])
        trace_ids = [e["trace_id"] for e in sample_embeddings]

        # Run clustering
        result = perform_kmeans_with_optimal_k(embeddings_array, min_k=2, max_k=5)

        # Compute distances once
        distances_matrix = calculate_trace_distances(embeddings_array, np.array(result.centroids))

        # Select representatives using pre-computed distances
        representatives = select_representatives_from_distances(
            np.array(result.labels), distances_matrix, trace_ids, n_closest=5
        )

        assert len(representatives) == len(result.centroids)
        for cluster_id, rep_ids in representatives.items():
            assert len(rep_ids) <= 5
            assert all(isinstance(tid, str) for tid in rep_ids)
            # Verify these are from the correct cluster
            cluster_mask = np.array(result.labels) == cluster_id
            cluster_trace_ids = [trace_ids[i] for i in range(len(trace_ids)) if cluster_mask[i]]
            assert all(tid in cluster_trace_ids for tid in rep_ids)


class TestDetermineOptimalKActivity:
    """Tests for determine_optimal_k_activity."""

    @pytest.mark.asyncio
    async def test_determine_optimal_k_success(self, sample_embeddings, mock_team):
        """Test optimal k determination."""
        # Note: This test would need actual ClickHouse data
        # For now, we skip integration tests that require database access
        pytest.skip("Skipping integration test - requires ClickHouse data")

    @pytest.mark.asyncio
    async def test_determine_optimal_k_insufficient_data(self):
        """Test with insufficient data."""
        # Note: This test would need actual ClickHouse data
        # For now, we skip integration tests that require database access
        pytest.skip("Skipping integration test - requires ClickHouse data")


class TestPerformClusteringActivity:
    """Tests for perform_clustering_activity."""

    @pytest.mark.asyncio
    async def test_clustering_success(self, sample_embeddings, mock_team):
        """Test clustering execution."""
        # Note: This test would need actual ClickHouse data
        # For now, we skip integration tests that require database access
        pytest.skip("Skipping integration test - requires ClickHouse data")


class TestEmitClusterEventsActivity:
    """Tests for emit_cluster_events_activity."""

    @pytest.mark.asyncio
    async def test_emit_events_success(self, sample_embeddings, mock_team):
        """Test event emission (placeholder)."""
        # Note: This test would need actual ClickHouse data
        # For now, we skip integration tests that require database access
        pytest.skip("Skipping integration test - requires ClickHouse data")


class TestWorkflowInputs:
    """Tests for workflow input models."""

    def test_clustering_inputs_defaults(self):
        """Test ClusteringInputs with default values."""
        inputs = ClusteringInputs(team_id=1, current_time="2025-01-01T00:00:00Z")

        assert inputs.team_id == 1
        assert inputs.lookback_days == 7
        assert inputs.max_samples == 5000
        assert inputs.min_k == 2
        assert inputs.max_k == 10

    def test_clustering_inputs_custom(self):
        """Test ClusteringInputs with custom values."""
        inputs = ClusteringInputs(
            team_id=1,
            current_time="2025-01-01T00:00:00Z",
            lookback_days=14,
            max_samples=5000,
            min_k=2,
            max_k=8,
            window_start="2025-01-01T00:00:00Z",
            window_end="2025-01-08T00:00:00Z",
        )

        assert inputs.lookback_days == 14
        assert inputs.max_samples == 5000
        assert inputs.window_start == "2025-01-01T00:00:00Z"
