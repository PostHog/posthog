from datetime import UTC, datetime, tzinfo
from typing import Any, Optional

from dateutil.parser import isoparse

from posthog.hogql import ast

from posthog.dataclasses import frozen
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
    resolved_query: ast.SelectQuery | ast.SelectSetQuery,
    *,
    now: datetime,
    timezone: tzinfo,
    week_start_day: Optional[int],
    relative_inputs: bool,
) -> SqlFreshness | Reject:
    try:
        facts = extract_facts(
            resolved_query,
            now=now,
            timezone=timezone,
            week_start_day=week_start_day,
            relative_inputs=relative_inputs,
        )
    except Exception:
        return Reject(reason=FreshnessReason.UNPARSEABLE)
    reason = reject_reason(facts)
    if reason is not None:
        return Reject(reason=reason)
    until, binding_reason = fresh_until(facts)
    return SqlFreshness(window=shortest_lived_window(facts), fresh_until=until.astimezone(UTC), reason=binding_reason)


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
