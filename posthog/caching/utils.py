from datetime import datetime
from dateutil.parser import isoparse
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from zoneinfo import ZoneInfo

from dateutil.parser import parser

import posthoganalytics


from posthog.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.datetime import start_of_day, start_of_hour, start_of_month, start_of_week
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


def active_teams() -> Set[int]:
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
    all_teams: List[Tuple[bytes, float]] = redis.zrange(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, 0, -1, withscores=True)
    if not all_teams:
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
            {team: score for team, score in teams_by_recency},
        )
        redis.expire(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, IN_A_DAY)
        all_teams = teams_by_recency

    return set(int(team_id) for team_id, _ in all_teams)


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


def is_stale_filter(
    team: Team,
    filter: Filter | RetentionFilter | StickinessFilter | PathFilter,
    cached_result: Any,
) -> bool:
    interval = filter.period.lower() if isinstance(filter, RetentionFilter) else filter.interval
    return is_stale(team, filter.date_to, interval, cached_result)


def is_stale(team: Team, date_to: datetime, interval: str, cached_result: Any) -> bool:
    """Indicates wether a cache item is obviously outdated based on the last
    requested date (date_to) and the granularity of the query (interval).
    It is considered outdated when the next time interval was entered since the
    last computation.
    """

    if stale_cache_invalidation_disabled(team):
        return False

    last_refresh = (
        cached_result.get("last_refresh", None) if isinstance(cached_result, Dict) else cached_result.last_refresh
    )
    date_to = min([date_to, datetime.now(tz=ZoneInfo("UTC"))])  # can't be later than now

    if last_refresh is None:
        raise Exception("Cached results require a last_refresh")

    if isinstance(last_refresh, str):
        last_refresh = isoparse(last_refresh)

    if interval == "hour":
        return start_of_hour(date_to) > start_of_hour(last_refresh)
    elif interval == "day":
        return start_of_day(date_to) > start_of_day(last_refresh)
    elif interval == "week":
        return start_of_week(date_to) > start_of_week(last_refresh)
    elif interval == "month":
        return start_of_month(date_to) > start_of_month(last_refresh)
    else:
        return False
