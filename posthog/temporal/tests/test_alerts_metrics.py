from datetime import UTC, datetime, timedelta

from unittest.mock import MagicMock, patch

from posthog.temporal.alerts.metrics import record_scheduler_fetch


def test_record_scheduler_fetch_emits_progress_and_saturation_signals() -> None:
    meter = MagicMock()
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

    with (
        patch("posthog.temporal.alerts.metrics.get_metric_meter", return_value=meter),
        patch("posthog.temporal.alerts.metrics.time.time", return_value=1_789_128_000.0),
    ):
        record_scheduler_fetch(
            selected_count=300,
            max_alerts_per_run=300,
            oldest_due_at=now - timedelta(minutes=45),
            now=now,
            has_more=True,
        )

    meter.with_additional_attributes.assert_called_once_with({"outcome": "saturated"})
    run_meter = meter.with_additional_attributes.return_value
    run_meter.create_counter.return_value.add.assert_called_once_with(1)
    meter.create_counter.return_value.add.assert_called_once_with(300)
    meter.create_gauge.return_value.set.assert_any_call(300)
    meter.create_gauge_float.return_value.set.assert_any_call(2_700.0)
    meter.create_gauge_float.return_value.set.assert_any_call(1_789_128_000.0)


def test_record_scheduler_fetch_resets_oldest_due_age_when_empty() -> None:
    meter = MagicMock()

    with (
        patch("posthog.temporal.alerts.metrics.get_metric_meter", return_value=meter),
        patch("posthog.temporal.alerts.metrics.time.time", return_value=1_789_128_000.0),
    ):
        record_scheduler_fetch(
            selected_count=0,
            max_alerts_per_run=300,
            oldest_due_at=None,
            now=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
            has_more=False,
        )

    meter.with_additional_attributes.assert_called_once_with({"outcome": "empty"})
    meter.create_gauge_float.return_value.set.assert_any_call(0.0)
