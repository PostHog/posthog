from datetime import UTC, datetime

from prometheus_client import Gauge


INSIGHT_ALERTS_DUE_COUNT = Gauge(
    "posthog_insight_alerts_due_count",
    "Number of insight alerts due for evaluation",
)
INSIGHT_ALERTS_OLDEST_DUE_AGE_SECONDS = Gauge(
    "posthog_insight_alerts_oldest_due_age_seconds",
    "Age of the oldest insight alert due for evaluation",
)
INSIGHT_ALERTS_SCHEDULER_LAST_POLL_TIMESTAMP_SECONDS = Gauge(
    "posthog_insight_alerts_scheduler_last_poll_timestamp_seconds",
    "Unix timestamp of the last successful insight alert scheduler poll",
)


def record_due_alert_metrics(*, due_count: int, oldest_due_at: datetime | None) -> None:
    now = datetime.now(UTC)
    INSIGHT_ALERTS_DUE_COUNT.set(due_count)
    INSIGHT_ALERTS_OLDEST_DUE_AGE_SECONDS.set(
        max(0, (now - oldest_due_at).total_seconds()) if oldest_due_at else 0
    )
    INSIGHT_ALERTS_SCHEDULER_LAST_POLL_TIMESTAMP_SECONDS.set(now.timestamp())
