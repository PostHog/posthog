from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Optional

from dateutil.parser import isoparse

from posthog.clickhouse.client import sync_execute
from posthog.interval_specs import INTERVAL_SPECS
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
from posthog.models.team.team import Team


def largest_teams(limit: int) -> set[int]:
    # nosemgrep: clickhouse-fstring-param-audit - events table comes from the internal schema gate
    teams_by_event_count = sync_execute(
        f"""
            SELECT team_id, COUNT(*) AS event_count
            FROM {events_read_table(use_new_events_schema(None))}
            WHERE timestamp > subtractDays(now(), 7)
            GROUP BY team_id
            ORDER BY event_count DESC
            LIMIT %(limit)s
        """,
        {"limit": limit},
    )
    return {int(team_id) for team_id, _ in teams_by_event_count}


def last_refresh_from_cached_result(cached_result: dict | object) -> Optional[datetime]:
    last_refresh: str | datetime | None
    if isinstance(cached_result, dict):
        last_refresh = cached_result.get("last_refresh")
    else:
        last_refresh = getattr(cached_result, "last_refresh", None)
    if isinstance(last_refresh, str):
        last_refresh = isoparse(last_refresh)
    return last_refresh


class ThresholdMode(Enum):
    DEFAULT = "default"
    LAZY = "lazy"
    AI = "ai"


staleness_threshold_map: dict[ThresholdMode, dict[Optional[str], timedelta]] = {
    ThresholdMode.DEFAULT: {
        None: timedelta(hours=6),
        **{name: spec.staleness_default for name, spec in INTERVAL_SPECS.items() if spec.staleness_default is not None},
    },
    ThresholdMode.LAZY: {
        None: timedelta(hours=12),
        **{name: spec.staleness_lazy for name, spec in INTERVAL_SPECS.items() if spec.staleness_lazy is not None},
    },
    ThresholdMode.AI: {
        None: timedelta(hours=1),
    },
}


def cache_target_age(
    interval: Optional[str], last_refresh: datetime, mode: ThresholdMode = ThresholdMode.DEFAULT
) -> Optional[datetime]:
    if interval not in staleness_threshold_map[mode]:
        return None
    return last_refresh + staleness_threshold_map[mode][interval]


def is_stale(
    team: Team,
    date_to: Optional[datetime],
    interval: Optional[str],
    last_refresh: Optional[datetime],
    mode: ThresholdMode = ThresholdMode.DEFAULT,
    target_age: Optional[datetime] = None,
) -> bool:
    """
    Indicates whether a cache item is obviously outdated based on the last_refresh date, the last
    requested date (date_to) and the granularity of the query (interval).
    """

    if last_refresh is None:
        raise ValueError("Cached results require a last_refresh")

    if target_age is not None:
        return datetime.now(UTC) > target_age

    # If the date_to is in the past of the last refresh, the data cannot be stale
    # Use a buffer in case last_refresh from cache.set happened slightly after the actual query
    if date_to and date_to < (last_refresh - timedelta(seconds=10)):
        return False

    max_age = cache_target_age(interval, last_refresh, mode)
    if not max_age:
        return False

    return datetime.now(UTC) > max_age
