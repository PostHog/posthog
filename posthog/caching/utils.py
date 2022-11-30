import datetime
from typing import List, Optional, Set, Tuple, Union

from dateutil.parser import parser

from posthog.client import sync_execute
from posthog.redis import get_client

RECENTLY_ACCESSED_TEAMS_REDIS_KEY = "INSIGHT_CACHE_UPDATE_RECENTLY_ACCESSED_TEAMS"

IN_A_DAY = 86_400


def ensure_is_date(candidate: Optional[Union[str, datetime.datetime]]) -> Optional[datetime.datetime]:
    if candidate is None:
        return None
    if isinstance(candidate, datetime.datetime):
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
        redis.zadd(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, {team: score for team, score in teams_by_recency})
        redis.expire(RECENTLY_ACCESSED_TEAMS_REDIS_KEY, IN_A_DAY)
        all_teams = teams_by_recency

    return set(int(team_id) for team_id, _ in all_teams)
