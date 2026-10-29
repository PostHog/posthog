from datetime import UTC, datetime, tzinfo
from typing import Any, Optional

from dateutil.parser import isoparse

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.hogql_queries.sql_freshness.facts import extract_facts
from posthog.hogql_queries.sql_freshness.rules import RULES, Cap, FreshnessReason, Reject, SqlWindowClass

API_SQL_WINDOW_CACHE_AGE_FLAG = "api-sql-window-cache-age"


@frozen
class SqlFreshness:
    window: SqlWindowClass
    fresh_until: datetime
    reason: FreshnessReason


def classify(
    resolved_query: ast.SelectQuery | ast.SelectSetQuery,
    *,
    now: datetime,
    timezone: tzinfo,
    week_start_day: Optional[int],
    relative_date_range: bool,
    rolling_filters: bool,
) -> SqlFreshness | Reject:
    """Any rejecting rule keeps the default age, otherwise the earliest cap wins, so rule order never changes the age."""
    try:
        facts = extract_facts(
            resolved_query,
            now=now,
            timezone=timezone,
            week_start_day=week_start_day,
            relative_date_range=relative_date_range,
            rolling_filters=rolling_filters,
        )
    except Exception:
        return Reject(reason=FreshnessReason.UNPARSEABLE)
    verdicts = [rule(facts) for rule in RULES]
    rejects = [verdict for verdict in verdicts if isinstance(verdict, Reject)]
    if rejects:
        return rejects[0]
    caps = [verdict for verdict in verdicts if isinstance(verdict, Cap)]
    binding = min(caps, key=lambda cap: cap.until)
    window = next(cap.window for cap in caps if cap.window is not None)
    return SqlFreshness(window=window, fresh_until=binding.until.astimezone(UTC), reason=binding.reason)


def freshness_record(freshness: SqlFreshness) -> dict[str, str]:
    return {
        "window": freshness.window.value,
        "fresh_until": freshness.fresh_until.isoformat(),
        "reason": freshness.reason.value,
    }


def freshness_from_record(record: Any) -> Optional[SqlFreshness]:
    try:
        return SqlFreshness(
            window=SqlWindowClass(record["window"]),
            fresh_until=isoparse(record["fresh_until"]),
            reason=FreshnessReason(record["reason"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
