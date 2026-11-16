import uuid
import dataclasses
from collections import namedtuple
from typing import Optional

from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Detail,
    LogActivityEntry,
    bulk_log_activity,
)
from posthog.models.activity_logging.personal_api_key_utils import get_organization_name, get_team_name
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import ai_credential_value

LogScope = namedtuple("LogScope", ["org_id", "team_id"])


@dataclasses.dataclass(frozen=True)
class ProjectSecretAPIKeyContext(ActivityContextBase):
    organization_name: Optional[str] = None
    project_name: Optional[str] = None
    scopes: Optional[list[str]] = None
    created_by_email: Optional[str] = None
    created_by_name: Optional[str] = None
    # Matches $ai_credential on gateway generations, so spend stays attributable after a delete or roll.
    ai_credential: Optional[str] = None
    # Set only when a roll changed the hash.
    previous_ai_credential: Optional[str] = None


def _ai_credential(api_key: Optional[ProjectSecretAPIKey]) -> Optional[str]:
    secure_value = getattr(api_key, "secure_value", None)
    return ai_credential_value(secure_value) if secure_value else None


def _get_team(api_key: ProjectSecretAPIKey) -> Optional[Team]:
    """Return the team for the given API key, fetching it if needed."""
    team = api_key.__dict__.get("team")
    team_id = getattr(api_key, "team_id", None)

    if team is not None and (team_id is None or team.id == team_id):
        return team

    if team_id is None:
        return None

    # The log entry reads only the team name, the organization id and the organization name,
    # so skip the rest of both wide rows.
    return (
        Team.objects.select_related("organization")
        .only("id", "name", "organization_id", "organization__id", "organization__name")
        .filter(id=team_id)
        .first()
    )


def _get_access_location(api_key: ProjectSecretAPIKey) -> tuple[LogScope, Optional[Team]]:
    team = _get_team(api_key)
    org_id = str(team.organization_id) if team and team.organization_id else None
    return LogScope(org_id, team.id if team else getattr(api_key, "team_id", None)), team


def log_project_secret_api_key_activity(
    api_key: ProjectSecretAPIKey,
    activity: str,
    user,
    was_impersonated: bool,
    changes=None,
    previous: Optional[ProjectSecretAPIKey] = None,
) -> None:
    """Create activity logs for ProjectSecretAPIKey operations scoped to the owning team."""
    location, team = _get_access_location(api_key)

    organization_name: Optional[str] = None
    if team and team.organization:
        organization_name = team.organization.name
    elif location.org_id:
        organization_name = get_organization_name(location.org_id)

    project_name = getattr(team, "name", None) or get_team_name(location.team_id)

    ai_credential = _ai_credential(api_key)
    previous_ai_credential = _ai_credential(previous)

    log_entries: list[LogActivityEntry] = []
    context = ProjectSecretAPIKeyContext(
        ai_credential=ai_credential,
        previous_ai_credential=previous_ai_credential if previous_ai_credential != ai_credential else None,
        organization_name=organization_name,
        project_name=project_name,
        scopes=list(api_key.scopes or []),
        created_by_email=getattr(api_key.created_by, "email", None),
        created_by_name=api_key.created_by.get_full_name()
        if api_key.created_by and api_key.created_by.get_full_name()
        else getattr(api_key.created_by, "email", None),
    )

    log_entries.append(
        {
            "organization_id": uuid.UUID(location.org_id) if location.org_id else None,
            "team_id": location.team_id,
            "user": user,
            "was_impersonated": was_impersonated,
            "item_id": api_key.id,
            "scope": "ProjectSecretAPIKey",
            "activity": activity,
            "detail": Detail(
                changes=changes,
                name=api_key.label,
                context=context,
            ),
        }
    )

    bulk_log_activity(log_entries)
