from datetime import UTC, datetime
from typing import TypedDict

from posthog.schema import AlertCalculationInterval

from posthog.slo.types import SloOutcome

ALERT_TIMELINESS_THRESHOLD_RATIO = 0.05
ALERT_TIMELINESS_MIN_THRESHOLD_SECONDS = 60
ALERT_TIMELINESS_MAX_THRESHOLD_SECONDS = 120

_ALERT_INTERVAL_SECONDS = {
    "every_minute": 60,
    AlertCalculationInterval.EVERY_15_MINUTES.value: 15 * 60,
    AlertCalculationInterval.HOURLY.value: 60 * 60,
    AlertCalculationInterval.DAILY.value: 24 * 60 * 60,
    AlertCalculationInterval.WEEKLY.value: 7 * 24 * 60 * 60,
    # Calendar months vary; the 120s cap means the exact long-interval value
    # does not affect the threshold, but keep a deterministic value for tests.
    AlertCalculationInterval.MONTHLY.value: 30 * 24 * 60 * 60,
}


class AlertTimelinessProperties(TypedDict):
    scheduled_due_at: str
    actual_check_start_at: str
    evaluation_lag_ms: int
    timeliness_threshold_ms: int
    is_late: bool


def alert_timeliness_threshold_ms(calculation_interval: str | None) -> int:
    """Return the allowed scheduler lag for an alert check in milliseconds.

    The agreed PostHog timeliness SLO is 5% of the alert interval, clamped
    between one scheduler tick (60s) and 120s. Unknown intervals use the max
    cap so a schema drift does not accidentally create an over-lenient target.
    """

    if calculation_interval is None:
        return ALERT_TIMELINESS_MAX_THRESHOLD_SECONDS * 1000

    interval_seconds = _ALERT_INTERVAL_SECONDS.get(calculation_interval)
    if interval_seconds is None:
        return ALERT_TIMELINESS_MAX_THRESHOLD_SECONDS * 1000

    threshold_seconds = interval_seconds * ALERT_TIMELINESS_THRESHOLD_RATIO
    threshold_seconds = max(ALERT_TIMELINESS_MIN_THRESHOLD_SECONDS, threshold_seconds)
    threshold_seconds = min(ALERT_TIMELINESS_MAX_THRESHOLD_SECONDS, threshold_seconds)
    return int(threshold_seconds * 1000)


def parse_scheduled_check_at(scheduled_check_at: str) -> datetime:
    parsed = datetime.fromisoformat(scheduled_check_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_alert_timeliness_completion(
    *,
    calculation_interval: str | None,
    scheduled_check_at: str,
    actual_check_start_at: datetime,
) -> tuple[SloOutcome, AlertTimelinessProperties]:
    scheduled_due_at = parse_scheduled_check_at(scheduled_check_at)
    actual_check_start_at = actual_check_start_at.astimezone(UTC)
    evaluation_lag_ms = max(0, int((actual_check_start_at - scheduled_due_at).total_seconds() * 1000))
    threshold_ms = alert_timeliness_threshold_ms(calculation_interval)
    is_late = evaluation_lag_ms > threshold_ms

    return (
        SloOutcome.FAILURE if is_late else SloOutcome.SUCCESS,
        {
            "scheduled_due_at": scheduled_due_at.isoformat(),
            "actual_check_start_at": actual_check_start_at.isoformat(),
            "evaluation_lag_ms": evaluation_lag_ms,
            "timeliness_threshold_ms": threshold_ms,
            "is_late": is_late,
        },
    )
