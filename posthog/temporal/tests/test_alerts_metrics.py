from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from unittest.mock import patch

from posthog.temporal.alerts.metrics import record_due_alert_metrics


def test_record_due_alert_metrics_records_due_count_oldest_age_and_poll_time() -> None:
    polled_at = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    alerts = [
        SimpleNamespace(next_check_at=polled_at - timedelta(minutes=30), created_at=polled_at - timedelta(days=1)),
        SimpleNamespace(next_check_at=None, created_at=polled_at - timedelta(hours=2)),
    ]

    with (
        patch("posthog.temporal.alerts.metrics.INSIGHT_ALERTS_DUE_COUNT.set") as due_count,
        patch("posthog.temporal.alerts.metrics.INSIGHT_ALERTS_OLDEST_DUE_AGE_SECONDS.set") as oldest_age,
        patch("posthog.temporal.alerts.metrics.INSIGHT_ALERTS_SCHEDULER_LAST_POLL_TIMESTAMP_SECONDS.set") as last_poll,
    ):
        record_due_alert_metrics(alerts, polled_at)

    due_count.assert_called_once_with(2)
    oldest_age.assert_called_once_with(7200)
    last_poll.assert_called_once_with(polled_at.timestamp())


def test_record_due_alert_metrics_resets_backlog_values_when_no_alerts_are_due() -> None:
    polled_at = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

    with (
        patch("posthog.temporal.alerts.metrics.INSIGHT_ALERTS_DUE_COUNT.set") as due_count,
        patch("posthog.temporal.alerts.metrics.INSIGHT_ALERTS_OLDEST_DUE_AGE_SECONDS.set") as oldest_age,
        patch("posthog.temporal.alerts.metrics.INSIGHT_ALERTS_SCHEDULER_LAST_POLL_TIMESTAMP_SECONDS.set") as last_poll,
    ):
        record_due_alert_metrics([], polled_at)

    due_count.assert_called_once_with(0)
    oldest_age.assert_called_once_with(0)
    last_poll.assert_called_once_with(polled_at.timestamp())
