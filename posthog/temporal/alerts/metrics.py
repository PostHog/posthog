from collections.abc import Iterable
from datetime import datetime

from prometheus_client import Gauge

from posthog.metrics import pushed_metrics_registry

from products.alerts.backend.models.alert import AlertConfiguration


def record_due_insight_alert_metrics(alerts: Iterable[AlertConfiguration], polled_at: datetime) -> None:
    due_count = 0
    oldest_due_at: datetime | None = None

    for alert in alerts:
        due_count += 1
        # A newly-created alert has no scheduled timestamp until its first
        # check. Its creation time is the best available lower bound for how
        # long it has been due; edits that make an alert due now persist a
        # concrete next_check_at timestamp at the write boundary.
        due_at = alert.next_check_at or alert.created_at or polled_at
        if oldest_due_at is None or due_at < oldest_due_at:
            oldest_due_at = due_at

    oldest_due_age_seconds: float = 0.0
    if oldest_due_at is not None:
        oldest_due_age_seconds = max((polled_at - oldest_due_at).total_seconds(), 0)

    with pushed_metrics_registry("temporal_insight_alerts") as registry:
        Gauge(
            "posthog_insight_alerts_due_count",
            "Number of enabled insight alerts due for evaluation",
            registry=registry,
        ).set(due_count)
        Gauge(
            "posthog_insight_alerts_oldest_due_age_seconds",
            "Age in seconds of the oldest due insight alert",
            registry=registry,
        ).set(oldest_due_age_seconds)
        Gauge(
            "posthog_insight_alerts_scheduler_last_poll_timestamp_seconds",
            "Unix timestamp of the last successful insight alert scheduler poll",
            registry=registry,
        ).set(polled_at.timestamp())
