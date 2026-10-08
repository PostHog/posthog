from datetime import datetime
from typing import Literal

from prometheus_client import Counter, Gauge

from posthog.metrics import pushed_metrics_registry

AiDetectorCheckOutcome = Literal["evaluated", "unavailable", "misconfigured"]

# Nothing else separates an AI detector check that reached a verdict from one whose provider
# was out of reach: both land as an errored check, and only the worker logs say which.
_AI_DETECTOR_CHECK_COUNTER = Counter(
    "posthog_insight_alerts_ai_detector_checks_total",
    "AI detector insight alert evaluations, by outcome",
    labelnames=["outcome"],
)


def record_ai_detector_check_outcome(outcome: AiDetectorCheckOutcome) -> None:
    _AI_DETECTOR_CHECK_COUNTER.labels(outcome=outcome).inc()


def record_due_insight_alert_metrics(due_count: int, oldest_due_at: datetime | None, polled_at: datetime) -> None:
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
