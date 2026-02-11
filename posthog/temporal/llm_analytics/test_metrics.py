import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.llm_analytics.metrics import (
    EVAL_ACTIVITY_TYPES,
    EVAL_WORKFLOW_TYPES,
    EvalsMetricsInterceptor,
    ExecutionTimeRecorder,
)


class TestExecutionTimeRecorder:
    def test_records_completed_status_on_success(self):
        """Test that ExecutionTimeRecorder records completed status when no exception"""
        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram_timedelta.return_value = mock_hist

        with patch("posthog.temporal.llm_analytics.metrics.get_metric_meter", return_value=mock_meter) as mock_get:
            with ExecutionTimeRecorder("test_histogram"):
                pass

            call_args = mock_get.call_args[0][0]
            assert call_args["status"] == "COMPLETED"
            assert call_args["exception"] == ""

    def test_records_failed_status_on_exception(self):
        """Test that ExecutionTimeRecorder records failed status when exception raised"""
        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram_timedelta.return_value = mock_hist

        with patch("posthog.temporal.llm_analytics.metrics.get_metric_meter", return_value=mock_meter) as mock_get:
            with pytest.raises(ValueError):
                with ExecutionTimeRecorder("test_histogram"):
                    raise ValueError("test error")

            call_args = mock_get.call_args[0][0]
            assert call_args["status"] == "FAILED"
            assert call_args["exception"] == "test error"

    def test_raises_if_not_entered(self):
        """Test that __exit__ raises if __enter__ was not called"""
        recorder = ExecutionTimeRecorder("test_histogram")
        with pytest.raises(RuntimeError, match="Start counter not initialized"):
            recorder.__exit__(None, None, None)

    def test_includes_histogram_attributes(self):
        """Test that additional histogram attributes are included"""
        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram_timedelta.return_value = mock_hist

        with patch("posthog.temporal.llm_analytics.metrics.get_metric_meter", return_value=mock_meter) as mock_get:
            with ExecutionTimeRecorder("test_histogram", histogram_attributes={"activity_type": "test_activity"}):
                pass

            call_args = mock_get.call_args[0][0]
            assert call_args["activity_type"] == "test_activity"
            assert call_args["status"] == "COMPLETED"
            assert call_args["exception"] == ""

    def test_set_status_overrides_default(self):
        """Test that set_status overrides the default COMPLETED status"""
        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram_timedelta.return_value = mock_hist

        with patch("posthog.temporal.llm_analytics.metrics.get_metric_meter", return_value=mock_meter) as mock_get:
            with ExecutionTimeRecorder("test_histogram") as recorder:
                recorder.set_status("SKIPPED")

            call_args = mock_get.call_args[0][0]
            assert call_args["status"] == "SKIPPED"
            assert call_args["exception"] == ""


class TestEvalsMetricsInterceptor:
    def test_interceptor_creates_activity_interceptor(self):
        """Test that the interceptor creates an activity interceptor"""
        interceptor = EvalsMetricsInterceptor()
        mock_next = MagicMock()
        result = interceptor.intercept_activity(mock_next)
        assert result is not None

    def test_interceptor_returns_workflow_interceptor_class(self):
        """Test that the interceptor returns a workflow interceptor class"""
        interceptor = EvalsMetricsInterceptor()
        mock_input = MagicMock()
        result = interceptor.workflow_interceptor_class(mock_input)
        assert result is not None


class TestActivityTypes:
    def test_eval_activity_types_contains_expected_activities(self):
        """Test that EVAL_ACTIVITY_TYPES contains the expected activities"""
        expected = {
            "fetch_evaluation_activity",
            "execute_llm_judge_activity",
            "emit_evaluation_event_activity",
            "emit_internal_telemetry_activity",
            "increment_trial_eval_count_activity",
            "update_key_state_activity",
        }
        assert EVAL_ACTIVITY_TYPES == expected

    def test_eval_workflow_types_contains_expected_workflows(self):
        """Test that EVAL_WORKFLOW_TYPES contains the expected workflows"""
        expected = {"run-evaluation"}
        assert EVAL_WORKFLOW_TYPES == expected
