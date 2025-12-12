"""Tests for trace clustering workflow."""

import pytest

import numpy as np

from posthog.temporal.llm_analytics.trace_clustering.clustering import (
    calculate_trace_distances,
    perform_kmeans_with_optimal_k,
    select_representatives_from_distances,
)
from posthog.temporal.llm_analytics.trace_clustering.models import (
    ClusteringActivityInputs,
    ClusteringComputeResult,
    ClusteringWorkflowInputs,
    ClusterLabel,
    EmitEventsActivityInputs,
    GenerateLabelsActivityInputs,
    GenerateLabelsActivityOutputs,
)


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

    def test_perform_kmeans_clamps_max_k_to_sample_count(self):
        """Test that max_k is clamped when it exceeds n_samples."""
        np.random.seed(42)
        # Only 5 samples, but max_k=10; silhouette requires k < n_samples
        embeddings = np.random.normal(0, 1, (5, 384))

        result = perform_kmeans_with_optimal_k(embeddings, min_k=2, max_k=10)

        # Should succeed with at most 4 clusters (n_samples - 1)
        assert 2 <= len(result.centroids) <= 4
        assert len(result.labels) == 5

    def test_perform_kmeans_raises_when_samples_at_or_below_min_k(self):
        """Test that ValueError is raised when n_samples <= min_k."""
        np.random.seed(42)
        # Only 5 samples, but min_k=5 (need at least 6 for silhouette to work)
        embeddings = np.random.normal(0, 1, (5, 384))

        with pytest.raises(ValueError, match="Cannot cluster 5 samples with min_k=5"):
            perform_kmeans_with_optimal_k(embeddings, min_k=5, max_k=10)


class TestWorkflowInputs:
    """Tests for workflow input models."""

    def test_workflow_inputs_defaults(self):
        """Test ClusteringWorkflowInputs with default values."""
        inputs = ClusteringWorkflowInputs(team_id=1)

        assert inputs.team_id == 1
        assert inputs.lookback_days == 7
        assert inputs.max_samples == 1000
        assert inputs.min_k == 2
        assert inputs.max_k == 10

    def test_workflow_inputs_custom(self):
        """Test ClusteringWorkflowInputs with custom values."""
        inputs = ClusteringWorkflowInputs(
            team_id=1,
            lookback_days=14,
            max_samples=1000,
            min_k=3,
            max_k=8,
        )

        assert inputs.team_id == 1
        assert inputs.lookback_days == 14
        assert inputs.max_samples == 1000
        assert inputs.min_k == 3
        assert inputs.max_k == 8

    def test_activity_inputs_required_fields(self):
        """Test ClusteringActivityInputs requires window bounds."""
        inputs = ClusteringActivityInputs(
            team_id=1,
            window_start="2025-01-01T00:00:00Z",
            window_end="2025-01-08T00:00:00Z",
        )

        assert inputs.team_id == 1
        assert inputs.window_start == "2025-01-01T00:00:00Z"
        assert inputs.window_end == "2025-01-08T00:00:00Z"
        assert inputs.max_samples == 1000
        assert inputs.min_k == 2
        assert inputs.max_k == 10


class TestActivityInputOutputModels:
    """Tests for activity input/output models."""

    def test_clustering_compute_result(self):
        """Test ClusteringComputeResult structure."""
        result = ClusteringComputeResult(
            clustering_run_id="1_20250108_000000",
            trace_ids=["trace_1", "trace_2", "trace_3"],
            labels=[0, 0, 1],
            centroids=[[1.0, 2.0], [3.0, 4.0]],
            distances=[[0.1, 0.9], [0.2, 0.8], [0.8, 0.1]],
            representative_trace_ids={0: ["trace_1"], 1: ["trace_3"]},
        )

        assert result.clustering_run_id == "1_20250108_000000"
        assert len(result.trace_ids) == 3
        assert len(result.labels) == 3
        assert len(result.centroids) == 2
        assert len(result.distances) == 3
        assert 0 in result.representative_trace_ids
        assert 1 in result.representative_trace_ids

    def test_generate_labels_activity_inputs(self):
        """Test GenerateLabelsActivityInputs structure."""
        inputs = GenerateLabelsActivityInputs(
            team_id=1,
            labels=[0, 0, 1, 1],
            representative_trace_ids={0: ["trace_1"], 1: ["trace_3"]},
            window_start="2025-01-01T00:00:00Z",
            window_end="2025-01-08T00:00:00Z",
        )

        assert inputs.team_id == 1
        assert len(inputs.labels) == 4
        assert inputs.representative_trace_ids[0] == ["trace_1"]
        assert inputs.window_start == "2025-01-01T00:00:00Z"
        assert inputs.window_end == "2025-01-08T00:00:00Z"

    def test_generate_labels_activity_outputs(self):
        """Test GenerateLabelsActivityOutputs structure."""
        outputs = GenerateLabelsActivityOutputs(
            cluster_labels={
                0: ClusterLabel(title="Pattern A", description="Description A"),
                1: ClusterLabel(title="Pattern B", description="Description B"),
            }
        )

        assert len(outputs.cluster_labels) == 2
        assert outputs.cluster_labels[0].title == "Pattern A"
        assert outputs.cluster_labels[1].description == "Description B"

    def test_emit_events_activity_inputs(self):
        """Test EmitEventsActivityInputs structure."""
        inputs = EmitEventsActivityInputs(
            team_id=1,
            clustering_run_id="1_20250108_000000",
            window_start="2025-01-01T00:00:00Z",
            window_end="2025-01-08T00:00:00Z",
            trace_ids=["trace_1", "trace_2"],
            labels=[0, 1],
            centroids=[[1.0, 2.0], [3.0, 4.0]],
            distances=[[0.1, 0.9], [0.8, 0.2]],
            cluster_labels={
                0: ClusterLabel(title="A", description="Desc A"),
                1: ClusterLabel(title="B", description="Desc B"),
            },
        )

        assert inputs.team_id == 1
        assert inputs.clustering_run_id == "1_20250108_000000"
        assert len(inputs.trace_ids) == 2
        assert len(inputs.labels) == 2
        assert len(inputs.centroids) == 2
        assert len(inputs.distances) == 2
        assert len(inputs.cluster_labels) == 2
