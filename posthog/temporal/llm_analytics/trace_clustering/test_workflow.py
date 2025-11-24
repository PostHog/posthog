"""Tests for trace clustering workflow."""

from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

import numpy as np

from posthog.temporal.llm_analytics.trace_clustering.activities import (
    determine_optimal_k_activity,
    emit_cluster_events_activity,
    perform_clustering_activity,
    query_trace_embeddings_activity,
    sample_embeddings_activity,
)
from posthog.temporal.llm_analytics.trace_clustering.clustering_utils import (
    determine_optimal_k,
    perform_kmeans_clustering,
    select_cluster_representatives,
)
from posthog.temporal.llm_analytics.trace_clustering.models import ClusteringInputs, TraceEmbedding


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
    """Generate sample embeddings for testing."""
    np.random.seed(42)
    embeddings = []

    # Create 100 embeddings in 3 clusters
    for i in range(30):
        # Cluster 0: around [1, 1, 1, ...]
        embedding = np.random.normal(1.0, 0.1, 384).tolist()
        embeddings.append(
            TraceEmbedding(
                trace_id=f"trace_0_{i}",
                embedding=embedding,
            )
        )

    for i in range(30):
        # Cluster 1: around [5, 5, 5, ...]
        embedding = np.random.normal(5.0, 0.1, 384).tolist()
        embeddings.append(
            TraceEmbedding(
                trace_id=f"trace_1_{i}",
                embedding=embedding,
            )
        )

    for i in range(40):
        # Cluster 2: around [10, 10, 10, ...]
        embedding = np.random.normal(10.0, 0.1, 384).tolist()
        embeddings.append(
            TraceEmbedding(
                trace_id=f"trace_2_{i}",
                embedding=embedding,
            )
        )

    return embeddings


class TestClusteringUtils:
    """Tests for clustering utility functions."""

    def test_determine_optimal_k_success(self, sample_embeddings):
        """Test optimal k determination with valid data."""
        embeddings_array = np.array([e.embedding for e in sample_embeddings])

        optimal_k, scores = determine_optimal_k(embeddings_array, min_k=2, max_k=5)

        assert 2 <= optimal_k <= 5
        assert len(scores) == 4  # k=2,3,4,5
        assert all(-1 <= score <= 1 for score in scores.values())
        # Should pick k=3 since we generated 3 clusters
        assert optimal_k == 3

    def test_determine_optimal_k_insufficient_data(self):
        """Test optimal k with insufficient data."""
        embeddings = np.random.rand(4, 384)  # Only 4 samples (less than MIN_TRACES_FOR_CLUSTERING=5)

        with pytest.raises(ValueError, match="Insufficient traces"):
            determine_optimal_k(embeddings, min_k=2, max_k=4)

    def test_perform_kmeans_clustering(self, sample_embeddings):
        """Test k-means clustering execution."""
        embeddings_array = np.array([e.embedding for e in sample_embeddings])

        labels, centroids, inertia = perform_kmeans_clustering(embeddings_array, k=3)

        assert len(labels) == len(sample_embeddings)
        assert centroids.shape == (3, 384)
        assert inertia > 0
        assert set(labels) == {0, 1, 2}  # Should have 3 clusters

    def test_select_cluster_representatives(self, sample_embeddings):
        """Test representative selection from clusters."""
        embeddings_array = np.array([e.embedding for e in sample_embeddings])
        trace_ids = [e.trace_id for e in sample_embeddings]

        # Run clustering
        labels, centroids, _ = perform_kmeans_clustering(embeddings_array, k=3)

        # Select representatives
        representatives = select_cluster_representatives(
            embeddings_array, labels, centroids, trace_ids, n_closest=5, n_random=2
        )

        assert len(representatives) == 3
        for _cluster_id, rep_ids in representatives.items():
            assert len(rep_ids) <= 7  # 5 closest + 2 random
            assert all(isinstance(tid, str) for tid in rep_ids)


class TestQueryTraceEmbeddingsActivity:
    """Tests for query_trace_embeddings_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_query_embeddings_success(self, mock_team):
        """Test successful embedding query."""
        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=7)

        with patch("posthog.clickhouse.client.execute.sync_execute") as mock_execute:
            # Mock query results
            mock_execute.return_value = [
                (
                    f"trace_{i}",
                    np.random.rand(384).tolist(),
                )
                for i in range(50)
            ]

            result = await query_trace_embeddings_activity(
                team_id=mock_team.id, window_start=start_dt.isoformat(), window_end=end_dt.isoformat()
            )

            assert len(result) == 50
            assert all(isinstance(e, TraceEmbedding) for e in result)
            assert result[0].trace_id == "trace_0"
            assert len(result[0].embedding) == 384

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_query_embeddings_empty(self, mock_team):
        """Test query when no embeddings found."""
        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=7)

        with patch("posthog.clickhouse.client.execute.sync_execute") as mock_execute:
            mock_execute.return_value = []

            result = await query_trace_embeddings_activity(
                team_id=mock_team.id, window_start=start_dt.isoformat(), window_end=end_dt.isoformat()
            )

            assert len(result) == 0


class TestSampleEmbeddingsActivity:
    """Tests for sample_embeddings_activity."""

    @pytest.mark.asyncio
    async def test_sample_below_max(self, sample_embeddings):
        """Test sampling when fewer embeddings than max."""
        result = await sample_embeddings_activity(sample_embeddings[:50], max_samples=100, random_seed=42)

        assert len(result) == 50  # Returns all
        assert result == sample_embeddings[:50]

    @pytest.mark.asyncio
    async def test_sample_above_max(self, sample_embeddings):
        """Test sampling when more embeddings than max."""
        result = await sample_embeddings_activity(sample_embeddings, max_samples=50, random_seed=42)

        assert len(result) == 50
        assert all(e in sample_embeddings for e in result)

    @pytest.mark.asyncio
    async def test_sample_reproducibility(self, sample_embeddings):
        """Test that sampling with same seed is reproducible."""
        result1 = await sample_embeddings_activity(sample_embeddings, max_samples=50, random_seed=42)
        result2 = await sample_embeddings_activity(sample_embeddings, max_samples=50, random_seed=42)

        assert result1 == result2


class TestDetermineOptimalKActivity:
    """Tests for determine_optimal_k_activity."""

    @pytest.mark.asyncio
    async def test_determine_optimal_k_success(self, sample_embeddings):
        """Test optimal k determination."""
        optimal_k, scores = await determine_optimal_k_activity(sample_embeddings, min_k=2, max_k=5)

        assert 2 <= optimal_k <= 5
        assert len(scores) == 4
        assert optimal_k == 3  # Should detect 3 clusters

    @pytest.mark.asyncio
    async def test_determine_optimal_k_insufficient_data(self):
        """Test with insufficient data."""
        # Create only 4 embeddings (less than MIN_TRACES_FOR_CLUSTERING=5)
        embeddings = [
            TraceEmbedding(
                trace_id=f"trace_{i}",
                embedding=np.random.rand(384).tolist(),
            )
            for i in range(4)
        ]

        with pytest.raises(ValueError):
            await determine_optimal_k_activity(embeddings, min_k=2, max_k=4)


class TestPerformClusteringActivity:
    """Tests for perform_clustering_activity."""

    @pytest.mark.asyncio
    async def test_clustering_success(self, sample_embeddings):
        """Test clustering execution."""
        labels, centroids, inertia = await perform_clustering_activity(sample_embeddings, k=3)

        assert len(labels) == len(sample_embeddings)
        assert len(centroids) == 3
        assert len(centroids[0]) == 384
        assert inertia > 0


class TestEmitClusterEventsActivity:
    """Tests for emit_cluster_events_activity."""

    @pytest.mark.asyncio
    async def test_emit_events_success(self, sample_embeddings, mock_team):
        """Test event emission (placeholder)."""
        # Run clustering first
        labels, centroids, inertia = await perform_clustering_activity(sample_embeddings, k=3)

        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=7)

        with patch("posthog.models.team.Team.objects.get") as mock_get_team:
            mock_get_team.return_value = mock_team

            result = await emit_cluster_events_activity(
                team_id=mock_team.id,
                clustering_run_id=f"team_{mock_team.id}_{end_dt.isoformat()}",
                window_start=start_dt.isoformat(),
                window_end=end_dt.isoformat(),
                total_traces=len(sample_embeddings),
                sampled_traces=len(sample_embeddings),
                optimal_k=3,
                silhouette_score=0.5,
                inertia=inertia,
                labels=labels,
                centroids=centroids,
                embeddings=sample_embeddings,
                cluster_labels={},
            )

        assert result == 1  # Should return 1 event emitted


class TestWorkflowInputs:
    """Tests for workflow input models."""

    def test_clustering_inputs_defaults(self):
        """Test ClusteringInputs with default values."""
        inputs = ClusteringInputs(team_id=1)

        assert inputs.team_id == 1
        assert inputs.lookback_days == 7
        assert inputs.max_samples == 100
        assert inputs.min_k == 2
        assert inputs.max_k == 4

    def test_clustering_inputs_custom(self):
        """Test ClusteringInputs with custom values."""
        inputs = ClusteringInputs(
            team_id=1,
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
