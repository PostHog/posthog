import datetime as dt

from unittest.mock import MagicMock, patch

from posthog.temporal.ai_observability.eval_reports.metrics import record_coordinator_poll


def test_record_coordinator_poll_emits_saturation_and_progress_signals() -> None:
    meter = MagicMock()
    oldest_due_at = dt.datetime(2026, 9, 11, 11, 0, tzinfo=dt.UTC)

    with (
        patch("posthog.temporal.ai_observability.eval_reports.metrics.activity.in_activity", return_value=True),
        patch(
            "posthog.temporal.ai_observability.eval_reports.metrics.get_metric_meter",
            return_value=meter,
        ) as get_meter,
        patch("posthog.temporal.ai_observability.eval_reports.metrics.time.time", return_value=1_789_128_000.0),
        patch(
            "posthog.temporal.ai_observability.eval_reports.metrics.dt.datetime",
            wraps=dt.datetime,
        ) as datetime_mock,
    ):
        datetime_mock.now.return_value = oldest_due_at + dt.timedelta(hours=1)
        record_coordinator_poll(
            selected_count=300,
            trigger_type="scheduled",
            has_more=True,
            oldest_due_at=oldest_due_at,
        )

    assert get_meter.call_args_list[0].args[0] == {"trigger_type": "scheduled", "outcome": "saturated"}
    metric_names = [call.args[0] for call in meter.method_calls if call[0].startswith("create_")]
    assert "llma_eval_reports_coordinator_polls" in metric_names
    assert "llma_eval_reports_coordinator_selected" in metric_names
    assert "llma_eval_reports_coordinator_oldest_due_age_seconds" in metric_names
    assert "llma_eval_reports_coordinator_last_successful_poll_timestamp_seconds" in metric_names
