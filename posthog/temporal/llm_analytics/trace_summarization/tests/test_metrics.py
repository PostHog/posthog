from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.trace_summarization.metrics import (
    SUMMARIZATION_ACTIVITY_TYPES,
    SUMMARIZATION_WORKFLOW_TYPES,
    SummarizationMetricsInterceptor,
    increment_embedding_result,
    increment_errors,
    increment_item_result,
    increment_skip,
    increment_workflow_finished,
    increment_workflow_started,
    record_items_sampled,
)


class TestActivityAndWorkflowTypes:
    def test_activity_types_match_actual_defns(self):
        from posthog.temporal.llm_analytics.trace_summarization.fetch_and_format import fetch_and_format_activity
        from posthog.temporal.llm_analytics.trace_summarization.sampling import sample_items_in_window_activity
        from posthog.temporal.llm_analytics.trace_summarization.summarize_and_save import summarize_and_save_activity

        actual_names = {
            sample_items_in_window_activity.__name__,
            fetch_and_format_activity.__name__,
            summarize_and_save_activity.__name__,
        }
        assert SUMMARIZATION_ACTIVITY_TYPES == actual_names

    def test_workflow_types_match_actual_defns(self):
        from posthog.temporal.llm_analytics.trace_summarization.constants import WORKFLOW_NAME

        assert SUMMARIZATION_WORKFLOW_TYPES == {WORKFLOW_NAME}


class TestSummarizationMetricsInterceptor:
    def test_creates_activity_interceptor(self):
        interceptor = SummarizationMetricsInterceptor()
        result = interceptor.intercept_activity(MagicMock())
        assert result is not None

    def test_returns_workflow_interceptor_class(self):
        interceptor = SummarizationMetricsInterceptor()
        result = interceptor.workflow_interceptor_class(MagicMock())
        assert result is not None


class TestCounterHelpers:
    @parameterized.expand(
        [
            ("increment_workflow_started", increment_workflow_started, ["trace"]),
            ("increment_workflow_finished", increment_workflow_finished, ["completed", "trace"]),
            ("record_items_sampled", record_items_sampled, [10, "trace"]),
            ("increment_item_result", increment_item_result, ["generated", "trace"]),
            ("increment_skip", increment_skip, ["trace_not_found", "trace"]),
            ("increment_embedding_result", increment_embedding_result, ["succeeded"]),
        ]
    )
    def test_counter_emits_in_temporal_context(self, _name, fn, args):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter

        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.metrics.get_metric_meter",
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
            patch("posthog.temporal.llm_analytics.trace_summarization.metrics.activity") as mock_activity,
            patch("posthog.temporal.llm_analytics.trace_summarization.metrics.workflow") as mock_workflow,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.metrics.get_metric_meter",
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
            patch("posthog.temporal.llm_analytics.trace_summarization.metrics.activity") as mock_activity,
            patch("posthog.temporal.llm_analytics.trace_summarization.metrics.workflow") as mock_workflow,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.metrics.get_metric_meter",
                return_value=mock_meter,
            ),
        ):
            mock_activity.in_activity.return_value = False
            mock_workflow.in_workflow.return_value = False

            increment_errors("test_error")

        mock_meter.create_counter.assert_not_called()
