import json
from typing import TYPE_CHECKING, Optional
from structlog import get_logger
from prometheus_client import Counter


from django.core.cache import cache
from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.models.team import Team

FIVE_DAYS = 60 * 60 * 24 * 5  # 5 days in seconds

logger = get_logger()


SET_TEAM_IN_CACHE_COUNTER = Counter(
    "set_team_in_cache_counter",
    "The number of times we've set a team in cache",
    labelnames=["success"],
)


def set_team_in_cache(token: str, team: Optional["Team"] = None) -> None:
    from posthog.api.team import CachingTeamSerializer
    from posthog.models.team import Team

    if not team:
        try:
            team = Team.objects.get(api_token=token)
        except (Team.DoesNotExist, Team.MultipleObjectsReturned):
            SET_TEAM_IN_CACHE_COUNTER.labels(success=False).inc()
            cache.delete(f"team_token:{token}")
            return

    serialized_team = CachingTeamSerializer(team).data

    # the serialized team should have many settings... if there are less than 6, something is wrong
    if len(serialized_team.keys()) <= 6:
        logger.error(
            f"Team {team.id} has no session recording URL config. It might be using an incorrectly serialized team.",
            team_id=team.id,
            token=token,
            serialized_team=serialized_team,
            stack_info=True,
        )

    cache.set(f"team_token:{token}", json.dumps(serialized_team), FIVE_DAYS)
    SET_TEAM_IN_CACHE_COUNTER.labels(success=True).inc()


def get_team_in_cache(token: str) -> Optional["Team"]:
    from posthog.models.team import Team

    try:
        team_data = cache.get(f"team_token:{token}")
    except Exception:
        # redis is unavailable
        return None

    if team_data:
        try:
            parsed_data = json.loads(team_data)
            if "project_id" not in parsed_data:
                parsed_data["project_id"] = parsed_data["id"]
            return Team(**parsed_data)
        except Exception as e:
            capture_exception(e)
            return None

    return None
