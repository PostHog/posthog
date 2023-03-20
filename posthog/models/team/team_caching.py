import json
from dataclasses import asdict, dataclass
from typing import List, Optional

from django.core.cache import cache
from sentry_sdk import capture_exception

from posthog.models.team import Team

FIVE_DAYS = 60 * 60 * 24 * 5  # 5 days in seconds


@dataclass
class CachedTeam:
    # NOTE: We use the CachedTeam for decide so that it is clear what limited Team properties are available.
    # If you add a property here you essentially invalidate the cache as deserialization will error forcing the caller to go
    # to the DB
    id: int
    uuid: str
    name: str
    api_token: str
    capture_console_log_opt_in: bool
    session_recording_opt_in: bool
    session_recording_version: str
    recording_domains: List[str]
    inject_web_apps: bool
    capture_performance_enabled: bool


def set_cached_team(token: str, team: Optional["Team"] = None) -> Optional[CachedTeam]:
    if not team:
        try:
            team = Team.objects.select_related("organization").get(api_token=token)
        except (Team.DoesNotExist, Team.MultipleObjectsReturned):
            cache.delete(f"team_token:{token}")
            return None

    serialized_team = CachedTeam(
        id=team.id,
        uuid=str(team.uuid),
        name=team.name,
        api_token=team.api_token,
        capture_console_log_opt_in=team.capture_console_log_opt_in,
        capture_performance_enabled=team.capture_performance_enabled,
        session_recording_opt_in=team.session_recording_opt_in,
        session_recording_version=team.session_recording_version,
        recording_domains=team.recording_domains,
        inject_web_apps=team.inject_web_apps,
    )

    cache.set(f"team_token:{token}", json.dumps(asdict(serialized_team)), FIVE_DAYS)

    return serialized_team


def get_cached_team(token: str) -> Optional[CachedTeam]:
    try:
        team_data = cache.get(f"team_token:{token}")
    except Exception:
        # redis is unavailable
        return None

    if team_data:
        try:
            parsed_data = CachedTeam(**json.loads(team_data))
            return parsed_data
        except TypeError:
            # This indicates that the deserialization failed so the cached schema didn't match
            # TODO: Add prometheus metric
            return None
        except Exception as e:
            capture_exception(e)
            return None

    return None


def get_or_set_cached_team(token: Optional[str]) -> Optional[CachedTeam]:
    if not token:
        return None
    try:
        cached_team = get_cached_team(token)
        if cached_team:
            return cached_team

        team = Team.objects.get(api_token=token)
        cached_team = set_cached_team(token, team)
        return cached_team

    except Team.DoesNotExist:
        return None
