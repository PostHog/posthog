import json
from typing import TYPE_CHECKING, Optional

from django.core.cache import cache

from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.models.team import Team

FIVE_DAYS = 60 * 60 * 24 * 5  # 5 days in seconds


def set_team_in_cache(token: str, team: Optional["Team"] = None) -> None:
    from posthog.api.team import CachingTeamSerializer
    from posthog.models.team import Team

    if not team:
        try:
            team = Team.objects.get(api_token=token)
        except (Team.DoesNotExist, Team.MultipleObjectsReturned):
            cache.delete(f"team_token:{token}")
            return

    serialized_team = CachingTeamSerializer(team).data

    cache.set(f"team_token:{token}", json.dumps(serialized_team), FIVE_DAYS)


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
