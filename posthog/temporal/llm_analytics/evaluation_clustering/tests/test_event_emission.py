"""Tests for $ai_evaluation_clusters event emission."""

import pytest
from unittest.mock import patch

import numpy as np

from posthog.temporal.llm_analytics.evaluation_clustering.constants import EVENT_NAME_EVALUATION_CLUSTERS
from posthog.temporal.llm_analytics.evaluation_clustering.event_emission import emit_evaluation_cluster_events
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterAggregateMetrics, ClusterItem, ClusterLabel


@pytest.fixture
def mock_team(db):
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    org = Organization.objects.create(name="Eval Emit Test Org")
    return Team.objects.create(organization=org, name="Eval Emit Test Team")


class TestEmitEvaluationClusterEvents:
    @pytest.mark.django_db(transaction=True)
    def test_emits_single_event_with_evaluation_level(self, mock_team):
        items = [
            ClusterItem(trace_id="e1", generation_id="e1"),
            ClusterItem(trace_id="e2", generation_id="e2"),
        ]
        labels = [0, 0]
        centroids = [[0.1, 0.2, 0.3]]
        distances = np.array([[0.5], [0.7]])
        coords_2d = np.array([[0.0, 0.0], [0.1, 0.1]])
        centroid_coords_2d = np.array([[0.05, 0.05]])
        cluster_labels = {0: ClusterLabel(title="Factuality failures", description="- shared hallucination pattern")}
        item_timestamps = {"e1": "2026-04-15T12:00:00Z", "e2": "2026-04-15T12:05:00Z"}

        with patch(
            "posthog.temporal.llm_analytics.evaluation_clustering.event_emission.create_event"
        ) as mock_create_event:
            clusters = emit_evaluation_cluster_events(
                team_id=mock_team.id,
                clustering_run_id="run-1",
                window_start="2026-04-15T00:00:00Z",
                window_end="2026-04-16T00:00:00Z",
                labels=labels,
                centroids=centroids,
                items=items,
                distances_matrix=distances,
                cluster_labels=cluster_labels,
                coords_2d=coords_2d,
                centroid_coords_2d=centroid_coords_2d,
                item_timestamps=item_timestamps,
                job_id="job-abc",
                job_name="Accuracy clustering",
            )

        assert len(clusters) == 1
        assert clusters[0].title == "Factuality failures"
        assert clusters[0].size == 2

        mock_create_event.assert_called_once()
        kwargs = mock_create_event.call_args.kwargs
        assert kwargs["event"] == EVENT_NAME_EVALUATION_CLUSTERS
        assert kwargs["distinct_id"] == f"clustering_evaluation_{mock_team.id}"

        props = kwargs["properties"]
        assert props["$ai_clustering_level"] == "evaluation"
        assert props["$ai_clustering_job_id"] == "job-abc"
        assert props["$ai_clustering_job_name"] == "Accuracy clustering"
        assert props["$ai_total_items_analyzed"] == 2
        assert props["$ai_clustering_run_id"] == "run-1"
        # Clusters are serialized as dicts
        assert props["$ai_clusters"][0]["title"] == "Factuality failures"

    @pytest.mark.django_db(transaction=True)
    def test_metrics_flow_through_to_cluster_payload(self, mock_team):
        items = [ClusterItem(trace_id="e1", generation_id="e1")]
        labels = [0]
        centroids = [[0.1]]
        distances = np.array([[0.0]])
        coords_2d = np.array([[0.0, 0.0]])
        centroid_coords_2d = np.array([[0.0, 0.0]])
        cluster_labels = {0: ClusterLabel(title="T", description="D")}
        cluster_metrics = {
            0: ClusterAggregateMetrics(
                avg_cost=0.01,
                error_rate=0.25,
                pass_rate=0.8,
                na_rate=0.1,
                dominant_evaluation_name="Accuracy",
                dominant_runtime="llm_judge",
                avg_judge_cost=0.001,
            )
        }

        with patch(
            "posthog.temporal.llm_analytics.evaluation_clustering.event_emission.create_event"
        ) as mock_create_event:
            clusters = emit_evaluation_cluster_events(
                team_id=mock_team.id,
                clustering_run_id="run-1",
                window_start="2026-04-15T00:00:00Z",
                window_end="2026-04-16T00:00:00Z",
                labels=labels,
                centroids=centroids,
                items=items,
                distances_matrix=distances,
                cluster_labels=cluster_labels,
                coords_2d=coords_2d,
                centroid_coords_2d=centroid_coords_2d,
                item_timestamps={"e1": "2026-04-15T12:00:00Z"},
                cluster_metrics=cluster_metrics,
            )

        assert clusters[0].metrics is not None
        assert clusters[0].metrics.pass_rate == 0.8
        assert clusters[0].metrics.dominant_evaluation_name == "Accuracy"

        props = mock_create_event.call_args.kwargs["properties"]
        cluster_payload = props["$ai_clusters"][0]
        assert cluster_payload["metrics"]["pass_rate"] == 0.8
        assert cluster_payload["metrics"]["dominant_runtime"] == "llm_judge"
        assert cluster_payload["metrics"]["avg_judge_cost"] == 0.001
