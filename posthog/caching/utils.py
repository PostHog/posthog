from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Optional, Union

import posthoganalytics
from dateutil.parser import isoparse, parser

from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team.team import Team
from posthog.redis import get_client

RECENTLY_ACCESSED_TEAMS_REDIS_KEY = "INSIGHT_CACHE_UPDATE_RECENTLY_ACCESSED_TEAMS"

IN_A_DAY = 86_400


def ensure_is_date(candidate: Optional[Union[str, datetime]]) -> Optional[datetime]:
    if candidate is None:
        return None
    if isinstance(candidate, datetime):
        return candidate
    return parser().parse(candidate)


def largest_teams(limit: int) -> set[int]:
    teams_by_event_count = sync_execute(
        """
            SELECT team_id, COUNT(*) AS event_count
            FROM events
            WHERE timestamp > subtractDays(now(), 7)
            GROUP BY team_id
            ORDER BY event_count DESC
            LIMIT %(limit)s
        """,
        {"limit": limit},
    )
    return {int(team_id) for team_id, _ in teams_by_event_count}


def active_teams() -> set[int]:
    """
    Teams are stored in a sorted set. [{team_id: score}, {team_id: score}].
    Their "score" is the number of seconds since last event.
    Lower is better.
    This lets us exclude teams not in the set as they don't have recent events.
    That is, if a team has not ingested events in the last seven days, why refresh its insights?
    And could let us process the teams in order of how recently they ingested events.
    This assumes that the list of active teams is small enough to reasonably load in one go.
    """
    redis = get_client()
    all_teams: list[tuple[bytes, float]] = redis.zrange(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, 0, -1, withscores=True)
    if not all_teams:
        # NOTE: `active_teams()` doesn't cooperate with freezegun (aka `freeze_time()`), because of
        # the ClickHouse `now()` function being used below
        teams_by_recency = sync_execute(
            """
            SELECT team_id, date_diff('second', max(timestamp), now()) AS age
            FROM events
            WHERE timestamp > date_sub(DAY, 3, now()) AND timestamp < now()
            GROUP BY team_id
            ORDER BY age;
        """
        )
        if not teams_by_recency:
            return set()
        redis.zadd(
            RECENTLY_ACCESSED_TEAMS_REDIS_KEY,
            dict(teams_by_recency),
        )
        redis.expire(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, IN_A_DAY)
        all_teams = teams_by_recency

    return {int(team_id) for team_id, _ in all_teams}


def stale_cache_invalidation_disabled(team: Team) -> bool:
    """Can be disabled temporarly to help in cases of service degradation."""
    if is_cloud():  # on PostHog Cloud, use the feature flag
        return not posthoganalytics.feature_enabled(
            "stale-cache-invalidation-enabled",
            str(team.uuid),
            groups={"organization": str(team.organization.id)},
            group_properties={
                "organization": {
                    "id": str(team.organization.id),
                    "created_at": team.organization.created_at,
                }
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    else:
        return False


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
        "minute": timedelta(minutes=5),
        "hour": timedelta(hours=1),
        "day": timedelta(hours=6),
        "week": timedelta(days=1),
        "month": timedelta(days=1),
    },
    ThresholdMode.LAZY: {
        None: timedelta(hours=12),
        "minute": timedelta(minutes=15),
        "hour": timedelta(hours=2),
        "day": timedelta(hours=12),
        "week": timedelta(days=1),
        "month": timedelta(days=1),
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

    if stale_cache_invalidation_disabled(team):
        return False

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
