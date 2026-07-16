"""Schedule restrictions (blocked local time windows) for insight alerts.

The pure minute-math and validation live in products/alerts/backend/calendar.py; this
module keeps the AlertConfiguration-aware entry points plus the cap-exceeded
retry/logging fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from products.alerts.backend.calendar import (
    MAX_BLOCKED_WINDOWS,
    MAX_UNBLOCK_STEPS,
    MIN_BLOCKED_WINDOW_MINUTES,
    MINUTES_PER_DAY,
    is_local_minute_blocked,
    is_utc_datetime_blocked as _is_utc_datetime_blocked_pure,
    merged_intervals_cover_full_day,
    normalize_schedule_restriction_value,
    parse_blocked_windows_tuples,
    scan_next_unblocked_utc,
    validate_and_normalize_schedule_restriction,
)
from products.alerts.backend.models.alert import AlertConfiguration

logger = structlog.get_logger(__name__)

# Module-level so tests can monkeypatch the cap; passed through to the pure scan.
_MAX_UNBLOCK_STEPS = MAX_UNBLOCK_STEPS

__all__ = [
    "MAX_BLOCKED_WINDOWS",
    "MINUTES_PER_DAY",
    "MIN_BLOCKED_WINDOW_MINUTES",
    "is_local_minute_blocked",
    "is_utc_datetime_blocked",
    "merged_intervals_cover_full_day",
    "next_unblocked_utc",
    "normalize_schedule_restriction_value",
    "parse_blocked_windows_tuples",
    "snap_candidate_utc_to_schedule_restriction",
    "validate_and_normalize_schedule_restriction",
]


def is_utc_datetime_blocked(alert: AlertConfiguration, dt_utc: datetime) -> bool:
    windows = parse_blocked_windows_tuples(alert.schedule_restriction)
    return _is_utc_datetime_blocked_pure(dt_utc, alert.team.timezone, windows)


def next_unblocked_utc(alert: AlertConfiguration, from_utc: datetime) -> datetime:
    """Smallest UTC instant >= from_utc (minute precision) when the alert is not in a blocked window."""
    return _next_unblocked_utc(alert, from_utc, recursion_depth=0)


def _next_unblocked_utc(
    alert: AlertConfiguration,
    from_utc: datetime,
    *,
    recursion_depth: int,
) -> datetime:
    windows = parse_blocked_windows_tuples(alert.schedule_restriction)
    found = scan_next_unblocked_utc(from_utc, alert.team.timezone, windows, max_steps=_MAX_UNBLOCK_STEPS)
    if found is not None:
        return found

    logger.warning(
        "schedule_restriction.next_unblocked_utc_exceeded_cap",
        alert_id=str(alert.id),
        recursion_depth=recursion_depth,
    )
    if recursion_depth >= 1:
        logger.error(
            "schedule_restriction.next_unblocked_utc_giving_up_after_retry",
            alert_id=str(alert.id),
        )
        return (from_utc.astimezone(UTC) + timedelta(days=1)).replace(microsecond=0)

    bump = from_utc.astimezone(UTC) + timedelta(days=1)
    return _next_unblocked_utc(alert, bump, recursion_depth=recursion_depth + 1)


def snap_candidate_utc_to_schedule_restriction(alert: AlertConfiguration, candidate_utc: datetime) -> datetime:
    if not alert.schedule_restriction:
        return candidate_utc
    normalized = candidate_utc.astimezone(UTC).replace(second=0, microsecond=0)
    return next_unblocked_utc(alert, normalized)
