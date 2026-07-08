from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Optional, Union

from dateutil.parser import isoparse, parser

from posthog.clickhouse.client import sync_execute
from posthog.interval_specs import INTERVAL_SPECS
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team.team import Team
from posthog.redis import get_client

RECENTLY_ACCESSED_TEAMS_REDIS_KEY = "INSIGHT_CACHE_UPDATE_RECENTLY_ACCESSED_TEAMS"
# Separate from the zset so an empty result has somewhere to land without a sentinel team.
RECENTLY_ACCESSED_TEAMS_POPULATED_KEY = "INSIGHT_CACHE_UPDATE_RECENTLY_ACCESSED_TEAMS_POPULATED"

IN_AN_HOUR = 3_600
IN_A_DAY = 86_400


def ensure_is_date(candidate: Optional[Union[str, datetime]]) -> Optional[datetime]:
    if candidate is None:
        return None
    if isinstance(candidate, datetime):
        return candidate
    return parser().parse(candidate)


def largest_teams(limit: int) -> set[int]:
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


def _populate_active_teams(redis) -> dict[int, float]:
    # NOTE: the ClickHouse `now()` function used here does not cooperate with freezegun.
    teams_by_recency = sync_execute(
        f"""
        SELECT team_id, date_diff('second', max(timestamp), now()) AS age
        FROM {events_read_table(use_new_events_schema(None))}
        WHERE timestamp > date_sub(DAY, 3, now()) AND timestamp < now()
        GROUP BY team_id
        ORDER BY age;
    """
    )
    teams = dict(teams_by_recency)
    # Marker is set even on empty results, so callers don't re-query for every inactive team.
    # Empty results get a shorter TTL so a newly-active team gets picked up within an hour.
    marker_ttl = IN_A_DAY if teams else IN_AN_HOUR
    pipe = redis.pipeline()
    if teams:
        pipe.zadd(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, teams)
        pipe.expire(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, IN_A_DAY)
    else:
        pipe.delete(RECENTLY_ACCESSED_TEAMS_REDIS_KEY)
    pipe.set(RECENTLY_ACCESSED_TEAMS_POPULATED_KEY, "1", ex=marker_ttl)
    pipe.execute()
    return teams


def is_team_active(team_id: int) -> bool:
    """
    O(log n) membership test on the recently-accessed-teams zset. Hot-path callers
    (signal-fired `sync_insight_caching_state` Celery tasks) should use this instead
    of `active_teams()` — one ZSCORE instead of a full ZRANGE of the set.
    """
    redis = get_client()
    score = redis.zscore(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, team_id)
    if score is not None:
        return True
    # ZSCORE None: either the team isn't recently active, or we haven't populated yet.
    if redis.exists(RECENTLY_ACCESSED_TEAMS_POPULATED_KEY):
        return False
    populated = _populate_active_teams(redis)
    return team_id in populated


def active_teams() -> set[int]:
    """
    Teams are stored in a sorted set. [{team_id: score}, {team_id: score}].
    Their "score" is the number of seconds since last event.
    Lower is better.
    This lets us exclude teams not in the set as they don't have recent events.
    That is, if a team has not ingested events in the last three days, why refresh its insights?
    And could let us process the teams in order of how recently they ingested events.
    This assumes that the list of active teams is small enough to reasonably load in one go.

    Retained for the batch path `sync_insight_cache_states()`, which genuinely iterates over
    every insight/tile and benefits from loading the set once. Do NOT use this on the
    signal-fired hot path — use `is_team_active()` instead.
    """
    redis = get_client()
    all_teams: list[tuple[bytes, float]] = redis.zrange(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, 0, -1, withscores=True)
    if all_teams:
        return {int(team_id) for team_id, _ in all_teams}
    if redis.exists(RECENTLY_ACCESSED_TEAMS_POPULATED_KEY):
        return set()
    teams = _populate_active_teams(redis)
    return set(teams.keys())


def last_refresh_from_cached_result(cached_result: dict | object) -> Optional[datetime]:
    last_refresh: str | datetime | None
    if isinstance(cached_result, dict):
        last_refresh = cached_result.get("last_refresh")
    else:
        last_refresh = getattr(cached_result, "last_refresh", None)
    if isinstance(last_refresh, str):
        last_refresh = isoparse(last_refresh)
    return last_refresh


def is_stale_filter(
    team: Team,
    filter: Filter | RetentionFilter | StickinessFilter | PathFilter,
    cached_result: Any,
) -> bool:
    interval = filter.period.lower() if isinstance(filter, RetentionFilter) else filter.interval
    last_refresh = last_refresh_from_cached_result(cached_result)
    return is_stale(team, filter.date_to, interval, last_refresh)


# enum legacy, default, lazy
class ThresholdMode(Enum):
    LEGACY = "legacy"
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
