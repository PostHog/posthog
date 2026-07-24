"""Team-timezone calendar-day math for the recompute oracle.

Python mirror of ``rust/cohort-core/src/bucket_tz.rs``. Every tz-date computation the oracle
needs routes through here so the window semantics have one source of truth and the
``toDate(param, tz)`` footgun below can never be reintroduced piecemeal.

Window boundary (the parity-critical decision): the pipeline's predicate is
``event_day >= now_day - N`` (``relative_date_parse("-Nd") == now - N days``), so "last N days"
is the **inclusive** set ``[at_day - N .. at_day]`` = ``N + 1`` day-buckets. :func:`window_dates`
returns those ``N + 1`` dates and :func:`window_start_utc` returns tz-midnight of ``at_day - N``.

DST (matches ``bucket_tz.rs``): instant -> day is always unambiguous, so :func:`day_of_instant`
is DST-exact. Day -> instant (:func:`start_of_day_utc`) can be ambiguous (fall-back) or
nonexistent (spring-forward gap); ``fold=0`` picks the **earliest** instant on a fall-back overlap
(= Python ``ZoneInfo`` fold=0) and lands on the **post-gap** instant for a skipped local midnight —
byte-for-byte the same UTC instant Rust's ``start_of_day_ms_in_tz`` returns.

The ``toDate(param, tz)`` footgun (cost hours in the 2026-07-24 canary): NEVER pass a Python-side
datetime through ClickHouse ``toDate(<datetime>, tz)`` — that re-interprets an already-UTC instant
in ``tz`` and shifts it a day. All tz-date arithmetic happens here in Python via ``ZoneInfo``; SQL
receives only UTC datetime params compared against ``e.timestamp``, or the tz *name* as a string
param inside ``toDate(<column>, %(tz)s)`` (converting a column is safe; converting a param is not).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_zoneinfo(name: str) -> ZoneInfo:
    """Parse an IANA tz name, falling back to UTC for an unrecognized one (matches the Rust loader's
    ``resolve_tz_or_utc``)."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def day_of_instant(instant: datetime, tz: ZoneInfo) -> date:
    """The team-tz calendar date of an aware instant. DST-exact (instant -> day is unambiguous)."""
    if instant.tzinfo is None:
        raise ValueError("day_of_instant requires an aware datetime")
    return instant.astimezone(tz).date()


def start_of_day_utc(day: date, tz: ZoneInfo) -> datetime:
    """tz-midnight of ``day`` as an aware UTC instant.

    ``fold=0`` matches Rust: earliest instant on a fall-back overlap, the post-gap instant on a
    spring-forward gap (a skipped civil day resolves to the following midnight, exactly as
    ``bucket_tz.rs``).
    """
    local_midnight = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz, fold=0)
    return local_midnight.astimezone(UTC)


# Saturation floor for an astronomical window: the earliest day a ClickHouse `DateTime64` event
# timestamp can hold, so the saturated bound still renders as a query parameter.
EPOCH_DAY = date(1970, 1, 1)


def window_start_day(at_day: date, window_days: int) -> date:
    """``at_day - N``, **saturating** at :data:`EPOCH_DAY` for an astronomical window.

    Mirrors ``bucket_tz.rs`` ``window_start_for_now``, which saturates to ``DayIdx::MIN`` rather than
    wrapping: an essentially infinite window covers everything and never evicts. Python would raise
    ``OverflowError`` instead. Defense in depth only — callers screen oversized windows before they
    drive a scan (see ``recompute.screen_for_recompute``).
    """
    if window_days < 0:
        raise ValueError("window_days must be non-negative")
    try:
        start = at_day - timedelta(days=window_days)
    except OverflowError:
        return EPOCH_DAY
    return max(start, EPOCH_DAY)


def window_dates(at: datetime, window_days: int, tz: ZoneInfo) -> list[date]:
    """The inclusive ``[at_day - N .. at_day]`` set = ``N + 1`` team-tz dates, ascending.

    ``window_days`` is the leaf's whole-day sliding window ``N``; the returned list has ``N + 1``
    entries (the ``+ 1`` is the off-by-one the pipeline's inclusive lower bound demands), unless the
    start saturates at :attr:`date.min`.
    """
    at_day = day_of_instant(at, tz)
    start = window_start_day(at_day, window_days)
    return [start + timedelta(days=offset) for offset in range((at_day - start).days + 1)]


def window_start_utc(at: datetime, window_days: int, tz: ZoneInfo) -> datetime:
    """UTC instant of tz-midnight of ``at_day - N`` — the inclusive window's lower bound.

    Paired with an ``e.timestamp <= at`` upper bound, ``e.timestamp >= window_start_utc(...)``
    selects exactly the whole-day window set without per-event day-bucketing.
    """
    return start_of_day_utc(window_start_day(day_of_instant(at, tz), window_days), tz)
