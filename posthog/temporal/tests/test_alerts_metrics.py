from collections.abc import Generator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from prometheus_client import CollectorRegistry

from posthog.temporal.alerts.metrics import record_due_insight_alert_metrics


def test_record_due_insight_alert_metrics_records_due_count_oldest_age_and_poll_time() -> None:
    polled_at = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    alerts = [
        SimpleNamespace(next_check_at=polled_at - timedelta(minutes=30), created_at=polled_at - timedelta(days=1)),
        SimpleNamespace(next_check_at=None, created_at=polled_at - timedelta(hours=2)),
    ]

    with _metrics_registry() as (pushed_registry, registry):
        record_due_insight_alert_metrics(alerts, polled_at)

    pushed_registry.assert_called_once_with("temporal_insight_alerts")
    assert registry.get_sample_value("posthog_insight_alerts_due_count") == 2
    assert registry.get_sample_value("posthog_insight_alerts_oldest_due_age_seconds") == 7200
    assert (
        registry.get_sample_value("posthog_insight_alerts_scheduler_last_poll_timestamp_seconds")
        == polled_at.timestamp()
    )


def test_record_due_insight_alert_metrics_resets_backlog_values_when_no_alerts_are_due() -> None:
    polled_at = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

    with _metrics_registry() as (_, registry):
        record_due_insight_alert_metrics([], polled_at)

    assert registry.get_sample_value("posthog_insight_alerts_due_count") == 0
    assert registry.get_sample_value("posthog_insight_alerts_oldest_due_age_seconds") == 0
    assert (
        registry.get_sample_value("posthog_insight_alerts_scheduler_last_poll_timestamp_seconds")
        == polled_at.timestamp()
    )


@contextmanager
def _metrics_registry() -> Generator[tuple[MagicMock, CollectorRegistry]]:
    registry = CollectorRegistry()

    with patch(
        "posthog.temporal.alerts.metrics.pushed_metrics_registry", return_value=nullcontext(registry)
    ) as pushed_registry:
        yield pushed_registry, registry
