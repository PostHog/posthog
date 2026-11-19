from datetime import UTC, datetime, tzinfo
from typing import Any, Optional

from dateutil.parser import isoparse

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.sql_freshness.facts import extract_facts
from posthog.hogql_queries.sql_freshness.rules import (
    FreshnessReason,
    Reject,
    SqlWindowClass,
    fresh_until,
    reject_reason,
    shortest_lived_window,
)


@frozen
class SqlFreshness:
    window: SqlWindowClass
    fresh_until: datetime
    reason: FreshnessReason


def classify(
    resolved_query: ast.SelectQuery | ast.SelectSetQuery, *, now: datetime, timezone: tzinfo
) -> SqlFreshness | Reject:
    try:
        facts = extract_facts(resolved_query, now=now, timezone=timezone)
        reason = reject_reason(facts)
        if reason is not None:
            return Reject(reason=reason)
        until, binding_reason = fresh_until(facts)
        window = shortest_lived_window(facts)
    except Exception as error:
        capture_exception(error, {"context": "sql_freshness_classification"})
        return Reject(reason=FreshnessReason.UNPARSEABLE)
    return SqlFreshness(window=window, fresh_until=until.astimezone(UTC), reason=binding_reason)


def freshness_record(freshness: SqlFreshness) -> dict[str, str]:
    return {
        "window": freshness.window.value,
        "fresh_until": freshness.fresh_until.isoformat(),
        "reason": freshness.reason.value,
    }


def freshness_from_record(record: Any) -> Optional[SqlFreshness]:
    try:
        fresh_until = isoparse(record["fresh_until"])
        if fresh_until.tzinfo is None:
            return None
        return SqlFreshness(
            window=SqlWindowClass(record["window"]),
            fresh_until=fresh_until,
            reason=FreshnessReason(record["reason"]),
        )
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return None
