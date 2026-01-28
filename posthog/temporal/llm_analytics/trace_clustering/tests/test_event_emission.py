"""Tests for event emission in trace clustering."""

import pytest
from unittest.mock import patch

import numpy as np
from parameterized import parameterized

from posthog.temporal.llm_analytics.trace_clustering.constants import NOISE_CLUSTER_ID
from posthog.temporal.llm_analytics.trace_clustering.event_emission import _build_cluster_data, emit_cluster_events
from posthog.temporal.llm_analytics.trace_clustering.models import (
    ClusterData,
    ClusterItem,
    ClusterLabel,
    TraceClusterMetadata,
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


class TestBuildClusterData:
    def test_builds_regular_clusters(self):
        labels = [0, 0, 1, 1]
        items = [
            ClusterItem(trace_id="trace_0", generation_id=None),
            ClusterItem(trace_id="trace_1", generation_id=None),
            ClusterItem(trace_id="trace_2", generation_id=None),
            ClusterItem(trace_id="trace_3", generation_id=None),
        ]
        distances_matrix = np.array(
            [
                [0.1, 0.9],  # trace_0 close to cluster 0
                [0.2, 0.8],  # trace_1 close to cluster 0
                [0.9, 0.1],  # trace_2 close to cluster 1
                [0.8, 0.2],  # trace_3 close to cluster 1
            ]
        )
        centroids = [[1.0, 0.0], [0.0, 1.0]]
        cluster_labels = {
            0: ClusterLabel(title="Cluster A", description="Description A"),
            1: ClusterLabel(title="Cluster B", description="Description B"),
        }
        coords_2d = np.array([[-1.0, 0.5], [-0.5, 0.6], [1.0, -0.3], [0.8, -0.4]])
        centroid_coords_2d = np.array([[-0.75, 0.55], [0.9, -0.35]])
        item_timestamps = {
            "trace_0": "2025-01-05T10:00:00",
            "trace_1": "2025-01-05T11:00:00",
            "trace_2": "2025-01-05T12:00:00",
            "trace_3": "2025-01-05T13:00:00",
        }

        clusters = _build_cluster_data(
            num_clusters=2,
            labels=labels,
            items=items,
            distances_matrix=distances_matrix,
            centroids=centroids,
            cluster_labels=cluster_labels,
            coords_2d=coords_2d,
            centroid_coords_2d=centroid_coords_2d,
            item_timestamps=item_timestamps,
        )

        assert len(clusters) == 2
        assert clusters[0].cluster_id == 0
        assert clusters[0].size == 2
        assert clusters[0].title == "Cluster A"
        assert "trace_0" in clusters[0].traces
        assert "trace_1" in clusters[0].traces

    def test_assigns_ranks_by_distance(self):
        labels = [0, 0, 0]
        items = [
            ClusterItem(trace_id="trace_far", generation_id=None),
            ClusterItem(trace_id="trace_close", generation_id=None),
            ClusterItem(trace_id="trace_mid", generation_id=None),
        ]
        distances_matrix = np.array([[0.9], [0.1], [0.5]])  # trace_close is nearest
        centroids = [[0.0, 0.0]]
        cluster_labels: dict[int, ClusterLabel] = {}
        coords_2d = np.array([[1.0, 0.0], [0.0, 0.0], [0.5, 0.0]])
        centroid_coords_2d = np.array([[0.0, 0.0]])
        item_timestamps: dict[str, str] = {}

        clusters = _build_cluster_data(
            num_clusters=1,
            labels=labels,
            items=items,
            distances_matrix=distances_matrix,
            centroids=centroids,
            cluster_labels=cluster_labels,
            coords_2d=coords_2d,
            centroid_coords_2d=centroid_coords_2d,
            item_timestamps=item_timestamps,
        )

        # Rank 0 should be trace_close (lowest distance)
        assert clusters[0].traces["trace_close"].rank == 0
        assert clusters[0].traces["trace_mid"].rank == 1
        assert clusters[0].traces["trace_far"].rank == 2

    def test_handles_noise_cluster(self):
        labels = [0, -1, -1]  # One regular cluster, two noise points
        items = [
            ClusterItem(trace_id="trace_0", generation_id=None),
            ClusterItem(trace_id="trace_noise_1", generation_id=None),
            ClusterItem(trace_id="trace_noise_2", generation_id=None),
        ]
        distances_matrix = np.array([[0.1], [0.8], [0.9]])  # Noise points far from centroid
        centroids = [[0.0, 0.0]]
        cluster_labels = {
            NOISE_CLUSTER_ID: ClusterLabel(title="Outliers", description="Anomalous traces"),
        }
        coords_2d = np.array([[0.0, 0.0], [5.0, 5.0], [6.0, 6.0]])
        centroid_coords_2d = np.array([[0.0, 0.0]])
        item_timestamps: dict[str, str] = {}

        clusters = _build_cluster_data(
            num_clusters=1,
            labels=labels,
            items=items,
            distances_matrix=distances_matrix,
            centroids=centroids,
            cluster_labels=cluster_labels,
            coords_2d=coords_2d,
            centroid_coords_2d=centroid_coords_2d,
            item_timestamps=item_timestamps,
        )

        assert len(clusters) == 2
        noise_cluster = next(c for c in clusters if c.cluster_id == NOISE_CLUSTER_ID)
        assert noise_cluster.size == 2
        assert noise_cluster.title == "Outliers"
        assert noise_cluster.centroid == []  # No actual centroid for noise
        assert "trace_noise_1" in noise_cluster.traces
        assert "trace_noise_2" in noise_cluster.traces

    def test_noise_cluster_ranks_by_highest_distance_first(self):
        labels = [-1, -1, -1]
        items = [
            ClusterItem(trace_id="trace_close", generation_id=None),
            ClusterItem(trace_id="trace_far", generation_id=None),
            ClusterItem(trace_id="trace_mid", generation_id=None),
        ]
        distances_matrix = np.array([[0.2], [0.9], [0.5]])
        centroids = [[0.0, 0.0]]
        cluster_labels: dict[int, ClusterLabel] = {}
        coords_2d = np.array([[0.5, 0.5], [3.0, 3.0], [1.5, 1.5]])
        centroid_coords_2d = np.array([[0.0, 0.0]])
        item_timestamps: dict[str, str] = {}

        clusters = _build_cluster_data(
            num_clusters=1,
            labels=labels,
            items=items,
            distances_matrix=distances_matrix,
            centroids=centroids,
            cluster_labels=cluster_labels,
            coords_2d=coords_2d,
            centroid_coords_2d=centroid_coords_2d,
            item_timestamps=item_timestamps,
        )

        noise_cluster = clusters[0]  # Only noise cluster since all points are noise
        # For noise, rank 0 should be the most anomalous (highest min distance)
        assert noise_cluster.traces["trace_far"].rank == 0
        assert noise_cluster.traces["trace_mid"].rank == 1
        assert noise_cluster.traces["trace_close"].rank == 2

    def test_uses_default_labels_when_not_provided(self):
        labels = [0, 1]
        items = [
            ClusterItem(trace_id="trace_0", generation_id=None),
            ClusterItem(trace_id="trace_1", generation_id=None),
        ]
        distances_matrix = np.array([[0.1, 0.9], [0.9, 0.1]])
        centroids = [[1.0, 0.0], [0.0, 1.0]]
        cluster_labels: dict[int, ClusterLabel] = {}  # No labels provided
        coords_2d = np.array([[0.0, 0.0], [1.0, 1.0]])
        centroid_coords_2d = np.array([[0.0, 0.0], [1.0, 1.0]])
        item_timestamps: dict[str, str] = {}

        clusters = _build_cluster_data(
            num_clusters=2,
            labels=labels,
            items=items,
            distances_matrix=distances_matrix,
            centroids=centroids,
            cluster_labels=cluster_labels,
            coords_2d=coords_2d,
            centroid_coords_2d=centroid_coords_2d,
            item_timestamps=item_timestamps,
        )

        assert clusters[0].title == "Cluster 0"
        assert clusters[1].title == "Cluster 1"

    def test_includes_trace_timestamps(self):
        labels = [0]
        items = [ClusterItem(trace_id="trace_0", generation_id=None)]
        distances_matrix = np.array([[0.1]])
        centroids = [[0.0]]
        cluster_labels: dict[int, ClusterLabel] = {}
        coords_2d = np.array([[0.0, 0.0]])
        centroid_coords_2d = np.array([[0.0, 0.0]])
        item_timestamps = {"trace_0": "2025-01-05T10:30:00"}

        clusters = _build_cluster_data(
            num_clusters=1,
            labels=labels,
            items=items,
            distances_matrix=distances_matrix,
            centroids=centroids,
            cluster_labels=cluster_labels,
            coords_2d=coords_2d,
            centroid_coords_2d=centroid_coords_2d,
            item_timestamps=item_timestamps,
        )

        assert clusters[0].traces["trace_0"].timestamp == "2025-01-05T10:30:00"

    def test_handles_empty_cluster(self):
        labels = [0, 0]  # All in cluster 0, none in cluster 1
        items = [
            ClusterItem(trace_id="trace_0", generation_id=None),
            ClusterItem(trace_id="trace_1", generation_id=None),
        ]
        distances_matrix = np.array([[0.1, 0.9], [0.2, 0.8]])
        centroids = [[1.0, 0.0], [0.0, 1.0]]
        cluster_labels: dict[int, ClusterLabel] = {}
        coords_2d = np.array([[0.0, 0.0], [0.1, 0.1]])
        centroid_coords_2d = np.array([[0.0, 0.0], [1.0, 1.0]])
        item_timestamps: dict[str, str] = {}

        clusters = _build_cluster_data(
            num_clusters=2,
            labels=labels,
            items=items,
            distances_matrix=distances_matrix,
            centroids=centroids,
            cluster_labels=cluster_labels,
            coords_2d=coords_2d,
            centroid_coords_2d=centroid_coords_2d,
            item_timestamps=item_timestamps,
        )

        # Only cluster 0 should be in results since cluster 1 is empty
        assert len(clusters) == 1
        assert clusters[0].cluster_id == 0


class TestEmitClusterEvents:
    @patch("posthog.temporal.llm_analytics.trace_clustering.event_emission.create_event")
    @patch("posthog.temporal.llm_analytics.trace_clustering.event_emission.fetch_item_summaries")
    def test_emits_event_with_correct_properties(self, mock_fetch_summaries, mock_create_event, mock_team):
        mock_fetch_summaries.return_value = {
            "trace_0": {"trace_timestamp": "2025-01-05T10:00:00"},
            "trace_1": {"trace_timestamp": "2025-01-05T11:00:00"},
        }

        items = [
            ClusterItem(trace_id="trace_0", generation_id=None),
            ClusterItem(trace_id="trace_1", generation_id=None),
        ]

        emit_cluster_events(
            team_id=mock_team.id,
            clustering_run_id="test_run_123",
            window_start="2025-01-01T00:00:00Z",
            window_end="2025-01-08T00:00:00Z",
            labels=[0, 0],
            centroids=[[1.0, 2.0]],
            items=items,
            distances_matrix=np.array([[0.1], [0.2]]),
            cluster_labels={0: ClusterLabel(title="Test Cluster", description="Test desc")},
            coords_2d=np.array([[0.0, 0.0], [0.1, 0.1]]),
            centroid_coords_2d=np.array([[0.05, 0.05]]),
        )

        mock_create_event.assert_called_once()
        call_kwargs = mock_create_event.call_args.kwargs
        assert call_kwargs["event"] == "$ai_trace_clusters"
        assert call_kwargs["team"].id == mock_team.id
        assert "$ai_clustering_run_id" in call_kwargs["properties"]
        assert call_kwargs["properties"]["$ai_clustering_run_id"] == "test_run_123"

    @patch("posthog.temporal.llm_analytics.trace_clustering.event_emission.create_event")
    @patch("posthog.temporal.llm_analytics.trace_clustering.event_emission.fetch_item_summaries")
    def test_returns_cluster_data_list(self, mock_fetch_summaries, mock_create_event, mock_team):
        mock_fetch_summaries.return_value = {}

        items = [
            ClusterItem(trace_id="trace_0", generation_id=None),
            ClusterItem(trace_id="trace_1", generation_id=None),
        ]

        clusters = emit_cluster_events(
            team_id=mock_team.id,
            clustering_run_id="test_run",
            window_start="2025-01-01T00:00:00Z",
            window_end="2025-01-08T00:00:00Z",
            labels=[0, 1],
            centroids=[[1.0], [2.0]],
            items=items,
            distances_matrix=np.array([[0.1, 0.9], [0.9, 0.1]]),
            cluster_labels={},
            coords_2d=np.array([[0.0, 0.0], [1.0, 1.0]]),
            centroid_coords_2d=np.array([[0.0, 0.0], [1.0, 1.0]]),
        )

        assert len(clusters) == 2
        assert all(isinstance(c, ClusterData) for c in clusters)

    def test_raises_on_invalid_datetime(self, mock_team):
        with pytest.raises(ValueError, match="Invalid datetime format"):
            emit_cluster_events(
                team_id=mock_team.id,
                clustering_run_id="test_run",
                window_start="invalid-date",
                window_end="2025-01-08T00:00:00Z",
                labels=[],
                centroids=[],
                items=[],
                distances_matrix=np.array([[]]),
                cluster_labels={},
                coords_2d=np.array([[]]),
                centroid_coords_2d=np.array([[]]),
            )


class TestClusterDataStructure:
    @parameterized.expand(
        [
            ("cluster_id", int),
            ("size", int),
            ("title", str),
            ("description", str),
            ("traces", dict),
            ("centroid", list),
            ("centroid_x", float),
            ("centroid_y", float),
        ]
    )
    def test_cluster_data_has_required_field(self, field_name, expected_type):
        cluster = ClusterData(
            cluster_id=0,
            size=10,
            title="Test Cluster",
            description="Test description",
            traces={
                "trace_1": TraceClusterMetadata(
                    rank=0, distance_to_centroid=0.1, x=0.0, y=0.0, timestamp="", trace_id="trace_1"
                )
            },
            centroid=[1.0, 2.0],
            centroid_x=0.5,
            centroid_y=0.5,
        )

        assert hasattr(cluster, field_name)
        assert isinstance(getattr(cluster, field_name), expected_type)
