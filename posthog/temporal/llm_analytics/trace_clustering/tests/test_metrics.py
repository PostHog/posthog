from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.trace_clustering.metrics import (
    CLUSTERING_ACTIVITY_TYPES,
    CLUSTERING_WORKFLOW_TYPES,
    ClusteringMetricsInterceptor,
    increment_errors,
    increment_workflow_finished,
    increment_workflow_started,
    record_clusters_generated,
    record_items_analyzed,
    record_noise_points,
)


class TestActivityAndWorkflowTypes:
    def test_activity_types_match_actual_defns(self):
        from posthog.temporal.llm_analytics.trace_clustering.activities import (
            emit_cluster_events_activity,
            generate_cluster_labels_activity,
            perform_clustering_compute_activity,
        )

        actual_names = {
            perform_clustering_compute_activity.__name__,
            generate_cluster_labels_activity.__name__,
            emit_cluster_events_activity.__name__,
        }
        assert CLUSTERING_ACTIVITY_TYPES == actual_names

    def test_workflow_types_match_actual_defns(self):
        from posthog.temporal.llm_analytics.trace_clustering.constants import WORKFLOW_NAME

        assert CLUSTERING_WORKFLOW_TYPES == {WORKFLOW_NAME}


class TestClusteringMetricsInterceptor:
    def test_creates_activity_interceptor(self):
        interceptor = ClusteringMetricsInterceptor()
        result = interceptor.intercept_activity(MagicMock())
        assert result is not None

    def test_returns_workflow_interceptor_class(self):
        interceptor = ClusteringMetricsInterceptor()
        result = interceptor.workflow_interceptor_class(MagicMock())
        assert result is not None


class TestCounterHelpers:
    @parameterized.expand(
        [
            ("increment_workflow_started", increment_workflow_started, ["trace"]),
            ("increment_workflow_finished", increment_workflow_finished, ["completed", "trace"]),
            ("record_items_analyzed", record_items_analyzed, [100, "trace"]),
            ("record_clusters_generated", record_clusters_generated, [5, "trace"]),
            ("record_noise_points", record_noise_points, [10, "trace"]),
        ]
    )
    def test_counter_emits_in_temporal_context(self, _name, fn, args):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter

        with patch(
            "posthog.temporal.llm_analytics.trace_clustering.metrics.get_metric_meter",
            return_value=mock_meter,
        ):
            fn(*args)

        mock_counter.add.assert_called_once()

    @parameterized.expand(
        [
            ("in_activity", True, False),
            ("in_workflow", False, True),
        ]
    )
    def test_increment_errors_emits_in_temporal_context(self, _name, in_act, in_wf):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter

        with (
            patch("posthog.temporal.llm_analytics.trace_clustering.metrics.activity") as mock_activity,
            patch("posthog.temporal.llm_analytics.trace_clustering.metrics.workflow") as mock_workflow,
            patch(
                "posthog.temporal.llm_analytics.trace_clustering.metrics.get_metric_meter",
                return_value=mock_meter,
            ),
        ):
            mock_activity.in_activity.return_value = in_act
            mock_workflow.in_workflow.return_value = in_wf

            increment_errors("test_error")

        mock_counter.add.assert_called_once_with(1)

    def test_increment_errors_noops_outside_temporal(self):
        mock_meter = MagicMock()

        with (
            patch("posthog.temporal.llm_analytics.trace_clustering.metrics.activity") as mock_activity,
            patch("posthog.temporal.llm_analytics.trace_clustering.metrics.workflow") as mock_workflow,
            patch(
                "posthog.temporal.llm_analytics.trace_clustering.metrics.get_metric_meter",
                return_value=mock_meter,
            ),
        ):
            mock_activity.in_activity.return_value = False
            mock_workflow.in_workflow.return_value = False

            increment_errors("test_error")

        mock_meter.create_counter.assert_not_called()
