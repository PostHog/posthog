"""Tests for trace clustering workflow."""

import uuid

import pytest

import numpy as np
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.llm_analytics.trace_clustering.clustering import perform_kmeans_with_optimal_k
from posthog.temporal.llm_analytics.trace_clustering.constants import DEFAULT_MAX_SAMPLES
from posthog.temporal.llm_analytics.trace_clustering.models import (
    ClusterAggregateMetrics,
    ClusteringActivityInputs,
    ClusteringComputeResult,
    ClusteringResult,
    ClusteringWorkflowInputs,
    ClusterItem,
    ClusterLabel,
    ComputeAggregatesActivityInputs,
    EmitEventsActivityInputs,
    GenerateLabelsActivityInputs,
    GenerateLabelsActivityOutputs,
    TraceLabelingMetadata,
)
from posthog.temporal.llm_analytics.trace_clustering.workflow import DailyTraceClusteringWorkflow


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
        assert inputs.max_samples == DEFAULT_MAX_SAMPLES
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
        assert inputs.max_samples == DEFAULT_MAX_SAMPLES
        assert inputs.min_k == 2
        assert inputs.max_k == 10


class TestActivityInputOutputModels:
    """Tests for activity input/output models."""

    def test_clustering_compute_result(self):
        """Test ClusteringComputeResult structure."""
        items = [
            ClusterItem(trace_id="trace_1"),
            ClusterItem(trace_id="trace_2"),
            ClusterItem(trace_id="trace_3"),
        ]
        result = ClusteringComputeResult(
            clustering_run_id="1_trace_20250108_000000",
            items=items,
            labels=[0, 0, 1],
            centroids=[[1.0, 2.0], [3.0, 4.0]],
            distances=[[0.1, 0.9], [0.2, 0.8], [0.8, 0.1]],
            coords_2d=[[-1.0, 0.5], [-0.5, 0.8], [1.5, -0.3]],
            centroid_coords_2d=[[-0.7, 0.6], [1.2, -0.2]],
            probabilities=[1.0, 1.0, 1.0],
        )

        assert result.clustering_run_id == "1_trace_20250108_000000"
        assert len(result.items) == 3
        assert len(result.labels) == 3
        assert len(result.centroids) == 2
        assert len(result.distances) == 3
        assert len(result.coords_2d) == 3
        assert len(result.centroid_coords_2d) == 2

    def test_generate_labels_activity_inputs(self):
        """Test GenerateLabelsActivityInputs structure."""
        items = [
            ClusterItem(trace_id="trace_1"),
            ClusterItem(trace_id="trace_2"),
            ClusterItem(trace_id="trace_3"),
            ClusterItem(trace_id="trace_4"),
        ]
        inputs = GenerateLabelsActivityInputs(
            team_id=1,
            items=items,
            labels=[0, 0, 1, 1],
            item_metadata=[
                TraceLabelingMetadata(x=-1.0, y=0.5, distance_to_centroid=0.1, rank=1),
                TraceLabelingMetadata(x=-0.8, y=0.6, distance_to_centroid=0.2, rank=2),
                TraceLabelingMetadata(x=1.2, y=-0.3, distance_to_centroid=0.15, rank=1),
                TraceLabelingMetadata(x=1.5, y=-0.5, distance_to_centroid=0.25, rank=2),
            ],
            centroid_coords_2d=[[-0.9, 0.55], [1.35, -0.4]],
            window_start="2025-01-01T00:00:00Z",
            window_end="2025-01-08T00:00:00Z",
        )

        assert inputs.team_id == 1
        assert len(inputs.items) == 4
        assert len(inputs.labels) == 4
        assert len(inputs.item_metadata) == 4
        assert inputs.item_metadata[0].rank == 1
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
        items = [
            ClusterItem(trace_id="trace_1"),
            ClusterItem(trace_id="trace_2"),
        ]
        inputs = EmitEventsActivityInputs(
            team_id=1,
            clustering_run_id="1_trace_20250108_000000",
            window_start="2025-01-01T00:00:00Z",
            window_end="2025-01-08T00:00:00Z",
            items=items,
            labels=[0, 1],
            centroids=[[1.0, 2.0], [3.0, 4.0]],
            distances=[[0.1, 0.9], [0.8, 0.2]],
            cluster_labels={
                0: ClusterLabel(title="A", description="Desc A"),
                1: ClusterLabel(title="B", description="Desc B"),
            },
            coords_2d=[[-1.0, 0.5], [1.5, -0.3]],
            centroid_coords_2d=[[-0.7, 0.6], [1.2, -0.2]],
        )

        assert inputs.team_id == 1
        assert inputs.clustering_run_id == "1_trace_20250108_000000"
        assert len(inputs.items) == 2
        assert len(inputs.labels) == 2
        assert len(inputs.centroids) == 2
        assert len(inputs.distances) == 2
        assert len(inputs.cluster_labels) == 2
        assert len(inputs.coords_2d) == 2
        assert len(inputs.centroid_coords_2d) == 2
        assert inputs.job_id == ""
        assert inputs.job_name == ""


class TestEmptyComputeResultShortCircuit:
    """Empty compute results must not trigger labeling/aggregates/emission.

    Emitting an empty $ai_*_clusters event would re-enroll the team in
    discovery for the next 30 days (see fix #1 in the loop bug analysis).
    """

    @staticmethod
    def _build_short_circuit_activities() -> dict[str, list[str]]:
        return {"calls": []}

    @pytest.mark.asyncio
    async def test_empty_compute_skips_label_aggregates_and_emit(self):
        calls: list[str] = []

        @activity.defn(name="perform_clustering_compute_activity")
        async def mock_compute(inputs: ClusteringActivityInputs) -> ClusteringComputeResult:
            calls.append("compute")
            return ClusteringComputeResult(
                clustering_run_id="run-empty",
                items=[],
                labels=[],
                centroids=[],
                distances=[],
                coords_2d=[],
                centroid_coords_2d=[],
                probabilities=[],
                analysis_level=inputs.analysis_level,
                num_noise_points=0,
                batch_run_ids={},
            )

        @activity.defn(name="generate_cluster_labels_activity")
        async def mock_labels(inputs: GenerateLabelsActivityInputs) -> GenerateLabelsActivityOutputs:
            calls.append("labels")
            return GenerateLabelsActivityOutputs(cluster_labels={})

        @activity.defn(name="compute_cluster_aggregates_activity")
        async def mock_aggregates(inputs: ComputeAggregatesActivityInputs) -> dict[int, ClusterAggregateMetrics]:
            calls.append("aggregates")
            return {}

        @activity.defn(name="emit_cluster_events_activity")
        async def mock_emit(inputs: EmitEventsActivityInputs) -> ClusteringResult:
            calls.append("emit")
            raise AssertionError("emit must not be called when compute returns no items")

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[DailyTraceClusteringWorkflow],
                activities=[mock_compute, mock_labels, mock_aggregates, mock_emit],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result: ClusteringResult = await env.client.execute_workflow(
                    DailyTraceClusteringWorkflow.run,
                    ClusteringWorkflowInputs(team_id=1, lookback_days=7),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert calls == ["compute"]
        assert result.metrics.total_items_analyzed == 0
        assert result.metrics.num_clusters == 0
        assert result.clusters == []
        assert result.clustering_run_id == "run-empty"
        assert result.team_id == 1
