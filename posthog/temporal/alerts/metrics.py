from collections.abc import Sequence
from datetime import datetime

from prometheus_client import Gauge

from products.alerts.backend.models.alert import AlertConfiguration

INSIGHT_ALERTS_DUE_COUNT = Gauge(
    "posthog_insight_alerts_due_count",
    "Number of enabled insight alerts due for evaluation",
)
INSIGHT_ALERTS_OLDEST_DUE_AGE_SECONDS = Gauge(
    "posthog_insight_alerts_oldest_due_age_seconds",
    "Age in seconds of the oldest due insight alert",
)
INSIGHT_ALERTS_SCHEDULER_LAST_POLL_TIMESTAMP_SECONDS = Gauge(
    "posthog_insight_alerts_scheduler_last_poll_timestamp_seconds",
    "Unix timestamp of the last successful insight alert scheduler poll",
)


def record_due_alert_metrics(alerts: Sequence[AlertConfiguration], polled_at: datetime) -> None:
    INSIGHT_ALERTS_DUE_COUNT.set(len(alerts))
    INSIGHT_ALERTS_SCHEDULER_LAST_POLL_TIMESTAMP_SECONDS.set(polled_at.timestamp())

    if not alerts:
        INSIGHT_ALERTS_OLDEST_DUE_AGE_SECONDS.set(0)
        return

    oldest_due_at = min(alert.next_check_at or alert.created_at for alert in alerts)
    INSIGHT_ALERTS_OLDEST_DUE_AGE_SECONDS.set(max((polled_at - oldest_due_at).total_seconds(), 0))
