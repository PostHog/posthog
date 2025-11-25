"""Tests for trace clustering workflow."""

import pytest

import numpy as np

from posthog.temporal.llm_analytics.trace_clustering.clustering_utils import (
    calculate_trace_distances,
    determine_optimal_k,
    perform_kmeans_clustering,
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

    def test_determine_optimal_k_success(self, sample_embeddings):
        """Test optimal k determination with valid data."""
        embeddings_array = np.array([e["embedding"] for e in sample_embeddings])

        optimal_k, scores = determine_optimal_k(embeddings_array, min_k=2, max_k=5)

        assert 2 <= optimal_k <= 5
        assert len(scores) == 4  # k=2,3,4,5
        assert all(-1 <= score <= 1 for score in scores.values())
        # Should pick k=3 since we generated 3 clusters
        assert optimal_k == 3

    def test_determine_optimal_k_insufficient_data(self):
        """Test optimal k with insufficient data."""
        embeddings = np.random.rand(10, 384)  # Only 10 samples (less than MIN_TRACES_FOR_CLUSTERING=20)

        with pytest.raises(ValueError, match="Insufficient traces"):
            determine_optimal_k(embeddings, min_k=3, max_k=6)

    def test_perform_kmeans_clustering(self, sample_embeddings):
        """Test k-means clustering execution."""
        embeddings_array = np.array([e["embedding"] for e in sample_embeddings])

        labels, centroids, inertia = perform_kmeans_clustering(embeddings_array, k=3)

        assert len(labels) == len(sample_embeddings)
        assert centroids.shape == (3, 384)
        assert inertia > 0
        assert set(labels) == {0, 1, 2}  # Should have 3 clusters

    def test_select_representatives_from_distances(self, sample_embeddings):
        """Test representative selection using pre-computed distances."""
        embeddings_array = np.array([e["embedding"] for e in sample_embeddings])
        trace_ids = [e["trace_id"] for e in sample_embeddings]

        # Run clustering
        labels, centroids, _ = perform_kmeans_clustering(embeddings_array, k=3)

        # Compute distances once
        distances_matrix = calculate_trace_distances(embeddings_array, centroids)

        # Select representatives using pre-computed distances
        representatives = select_representatives_from_distances(labels, distances_matrix, trace_ids, n_closest=5)

        assert len(representatives) == 3
        for cluster_id, rep_ids in representatives.items():
            assert len(rep_ids) <= 5
            assert all(isinstance(tid, str) for tid in rep_ids)
            # Verify these are from the correct cluster
            cluster_mask = labels == cluster_id
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
        assert inputs.max_samples == 2000
        assert inputs.min_k == 3
        assert inputs.max_k == 6

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
