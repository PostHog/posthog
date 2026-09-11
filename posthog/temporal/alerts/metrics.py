import time
from datetime import datetime

from posthog.temporal.common.metrics import get_metric_meter

SCHEDULER_RUNS = "insight_alert_scheduler_runs"
SCHEDULER_SELECTED = "insight_alert_scheduler_selected"
SCHEDULER_MAX_ALERTS_PER_RUN = "insight_alert_scheduler_max_alerts_per_run"
SCHEDULER_OLDEST_DUE_AGE_SECONDS = "insight_alert_scheduler_oldest_due_age_seconds"
SCHEDULER_LAST_SUCCESSFUL_FETCH_TIMESTAMP_SECONDS = "insight_alert_scheduler_last_successful_fetch_timestamp_seconds"


def record_scheduler_fetch(
    *,
    selected_count: int,
    max_alerts_per_run: int,
    oldest_due_at: datetime | None,
    now: datetime,
    has_more: bool,
) -> None:
    """Record bounded scheduler progress without tenant-level labels."""
    meter = get_metric_meter()
    outcome = "saturated" if has_more else "empty" if selected_count == 0 else "partial"
    meter.with_additional_attributes({"outcome": outcome}).create_counter(
        SCHEDULER_RUNS,
        "Insight alert scheduler fetches by whether the configured batch was exhausted.",
    ).add(1)
    meter.create_counter(
        SCHEDULER_SELECTED,
        "Due insight alerts selected for Temporal child-workflow dispatch.",
    ).add(selected_count)
    meter.create_gauge(
        SCHEDULER_MAX_ALERTS_PER_RUN,
        "Effective per-run insight alert selection limit.",
    ).set(max_alerts_per_run)
    oldest_due_age_seconds = max(0.0, (now - oldest_due_at).total_seconds()) if oldest_due_at is not None else 0.0
    meter.create_gauge_float(
        SCHEDULER_OLDEST_DUE_AGE_SECONDS,
        "Age in seconds of the oldest due insight alert selected by a scheduler run.",
        "s",
    ).set(oldest_due_age_seconds)
    meter.create_gauge_float(
        SCHEDULER_LAST_SUCCESSFUL_FETCH_TIMESTAMP_SECONDS,
        "Unix timestamp of the last successful insight alert scheduler fetch.",
    ).set(time.time())
