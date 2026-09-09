from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from posthog.temporal.alerts.metrics import record_due_alert_metrics


def test_record_due_alert_metrics_records_due_count_oldest_age_and_poll_time() -> None:
    polled_at = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    alerts = [
        SimpleNamespace(next_check_at=polled_at - timedelta(minutes=30), created_at=polled_at - timedelta(days=1)),
        SimpleNamespace(next_check_at=None, created_at=polled_at - timedelta(hours=2)),
    ]

    with _patch_metrics() as (pushed_registry, due_count, oldest_age, last_poll):
        record_due_alert_metrics(alerts, polled_at)

    pushed_registry.assert_called_once_with("temporal_insight_alerts")
    due_count.set.assert_called_once_with(2)
    oldest_age.set.assert_called_once_with(7200)
    last_poll.set.assert_called_once_with(polled_at.timestamp())


def test_record_due_alert_metrics_resets_backlog_values_when_no_alerts_are_due() -> None:
    polled_at = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

    with _patch_metrics() as (_, due_count, oldest_age, last_poll):
        record_due_alert_metrics([], polled_at)

    due_count.set.assert_called_once_with(0)
    oldest_age.set.assert_called_once_with(0)
    last_poll.set.assert_called_once_with(polled_at.timestamp())


@contextmanager
def _patch_metrics() -> Generator[tuple[MagicMock, MagicMock, MagicMock, MagicMock]]:
    gauges = [MagicMock(), MagicMock(), MagicMock()]
    registry = MagicMock()

    with (
        patch("posthog.temporal.alerts.metrics.pushed_metrics_registry") as pushed_registry,
        patch("posthog.temporal.alerts.metrics.Gauge", side_effect=gauges),
    ):
        pushed_registry.return_value.__enter__.return_value = registry
        yield (pushed_registry, *gauges)
