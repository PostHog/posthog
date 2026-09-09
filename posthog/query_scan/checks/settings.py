"""Checks for insight kinds that are built from pickers instead of SQL.

These read the query dict, because the problem is a setting the person chose, and the advice
names the picker rather than a clause.
"""

from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen

# Retention builds its series differently and is left out of v1.
_SERIES_QUERY_KINDS = frozenset({"TrendsQuery", "FunnelsQuery", "StickinessQuery", "LifecycleQuery"})

_ALL_TIME_DATE_FROM = "all"


@frozen
class SettingsOutcome:
    all_events: bool
    all_time: bool


def check_settings(query: Mapping[str, Any]) -> SettingsOutcome:
    return SettingsOutcome(all_events=_has_all_events_series(query), all_time=_has_all_time_range(query))


def _has_all_events_series(query: Mapping[str, Any]) -> bool:
    if query.get("kind") not in _SERIES_QUERY_KINDS:
        return False
    series = query.get("series")
    if not isinstance(series, list):
        return False
    return any(
        isinstance(entry, Mapping) and entry.get("kind") == "EventsNode" and entry.get("event") is None
        for entry in series
    )


def _has_all_time_range(query: Mapping[str, Any]) -> bool:
    date_range = query.get("dateRange")
    return isinstance(date_range, Mapping) and date_range.get("date_from") == _ALL_TIME_DATE_FROM
