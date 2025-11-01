import uuid
import dataclasses
from collections import namedtuple
from typing import Optional

from django.db.models import Count

from posthog.models import PersonalAPIKey
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Detail,
    LogActivityEntry,
    bulk_log_activity,
)
from posthog.models.team.team import Team
from posthog.user_permissions import UserPermissions

LogScope = namedtuple("LogScope", ["org_id", "team_id"])


@dataclasses.dataclass(frozen=True)
class PersonalAPIKeyContext(ActivityContextBase):
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    organization_name: Optional[str] = None
    team_name: Optional[str] = None


def get_personal_api_key_access_locations(api_key: PersonalAPIKey) -> set[LogScope]:
    """Calculate where activity logs should be created for a PersonalAPIKey based on its scope."""
    if api_key.scoped_teams:
        teams = Team.objects.filter(pk__in=api_key.scoped_teams).select_related("organization")
        return {LogScope(str(team.organization_id), team.id) for team in teams}
    elif api_key.scoped_organizations:
        return {LogScope(str(org_id), None) for org_id in api_key.scoped_organizations}
    else:
        user_permissions = UserPermissions(api_key.user)
        return {LogScope(str(org_id), None) for org_id in user_permissions.organization_memberships.keys()}


def calculate_access_set(api_key: PersonalAPIKey) -> set[LogScope]:
    """Legacy wrapper for get_personal_api_key_access_locations."""
    return get_personal_api_key_access_locations(api_key)


def expand_org_access_to_teams(api_key: PersonalAPIKey, org_ids: list[str]) -> set[LogScope]:
    """Expand organization-level access to all teams within those orgs."""
    if not org_ids:
        return set()

    teams = Team.objects.filter(organization_id__in=org_ids).values("id", "organization_id")
    return {LogScope(str(team["organization_id"]), team["id"]) for team in teams}


def get_org_team_counts(org_ids: list[str]) -> dict[str, int]:
    """Get the number of teams in each organization."""
    org_counts = (
        Team.objects.filter(organization_id__in=org_ids).values("organization_id").annotate(team_count=Count("id"))
    )
    return {str(item["organization_id"]): item["team_count"] for item in org_counts}


def team_represents_entire_org(team_locations: set[LogScope]) -> dict[str, bool]:
    """Check if each team represents the entire organization (is the only team in that org)."""
    if not team_locations:
        return {}

    org_ids = list({loc.org_id for loc in team_locations})
    org_team_counts = get_org_team_counts(org_ids)

    result = {}
    for location in team_locations:
        total_teams_in_org = org_team_counts.get(location.org_id, 0)
        result[f"{location.org_id}:{location.team_id}"] = total_teams_in_org == 1

    return result


def get_teams_representing_full_orgs(lost_access: set[LogScope]) -> set[str]:
    """Get organization IDs where all teams are being revoked (should be org-level revocation)."""
    if not lost_access:
        return set()

    org_lost_teams: dict[str, set[int]] = {}
    for location in lost_access:
        if location.team_id is not None:
            if location.org_id not in org_lost_teams:
                org_lost_teams[location.org_id] = set()
            org_lost_teams[location.org_id].add(location.team_id)

    if not org_lost_teams:
        return set()

    org_ids = list(org_lost_teams.keys())
    org_team_counts = get_org_team_counts(org_ids)

    full_org_revocations = set()
    for org_id, lost_team_ids in org_lost_teams.items():
        total_teams = org_team_counts.get(org_id, 0)
        if total_teams > 0 and len(lost_team_ids) == total_teams:
            full_org_revocations.add(org_id)

    return full_org_revocations


def calculate_scope_change_logs(before_api_key: PersonalAPIKey, after_api_key: PersonalAPIKey, changes) -> list[dict]:
    """Calculate all activity logs needed for a scope change.

    Returns only 'created' and 'revoked' activities:
    - 'created': New access gained to a location
    - 'revoked': Access lost from a location
    - NO 'updated' activities for scope changes
    - Handles edge cases for single-team organizations and full-org revocations
    """
    before_access = calculate_access_set(before_api_key)
    after_access = calculate_access_set(after_api_key)

    if not before_api_key.scoped_teams and before_api_key.scoped_organizations and after_api_key.scoped_teams:
        before_access = expand_org_access_to_teams(before_api_key, before_api_key.scoped_organizations)

    logs = []

    gained = after_access - before_access

    filtered_gained = set()
    for location in gained:
        if location.team_id is None:
            equivalent_team_access_before = any(
                before_loc.org_id == location.org_id and before_loc.team_id is not None for before_loc in before_access
            )
            if equivalent_team_access_before:
                before_teams_in_org = {
                    before_loc
                    for before_loc in before_access
                    if before_loc.org_id == location.org_id and before_loc.team_id is not None
                }
                team_equivalency = team_represents_entire_org(before_teams_in_org)
                if any(team_equivalency.values()):
                    continue

        filtered_gained.add(location)

    for location in filtered_gained:
        logs.append(
            {"organization_id": location.org_id, "team_id": location.team_id, "activity": "created", "type": None}
        )

    lost = before_access - after_access
    full_org_revocations = get_teams_representing_full_orgs(lost)

    filtered_lost = set()
    for location in lost:
        if location.team_id is not None and location.org_id in full_org_revocations:
            continue
        filtered_lost.add(location)

    for org_id in full_org_revocations:
        filtered_lost.add(LogScope(org_id, None))

    for location in filtered_lost:
        logs.append(
            {"organization_id": location.org_id, "team_id": location.team_id, "activity": "revoked", "type": None}
        )

    return logs


def log_personal_api_key_scope_change(
    before_api_key: PersonalAPIKey, after_api_key: PersonalAPIKey, user, was_impersonated: bool, changes
):
    """Log activity for PersonalAPIKey scope changes with proper created/revoked logic."""
    log_entries = calculate_scope_change_logs(before_api_key, after_api_key, changes)

    bulk_entries: list[LogActivityEntry] = []
    for log_entry in log_entries:
        team_id = log_entry["team_id"]
        org_id = log_entry["organization_id"]

        detail_data = Detail(
            changes=changes,
            name=after_api_key.label,
            context=PersonalAPIKeyContext(
                user_id=after_api_key.user_id,
                user_email=after_api_key.user.email,
                user_name=after_api_key.user.get_full_name(),
                organization_name=get_organization_name(log_entry["organization_id"])
                if log_entry["organization_id"]
                else None,
                team_name=get_team_name(team_id) if team_id else None,
            ),
        )

        bulk_entries.append(
            {
                "organization_id": uuid.UUID(org_id),
                "team_id": team_id,
                "user": user,
                "was_impersonated": was_impersonated,
                "item_id": after_api_key.id,
                "scope": "PersonalAPIKey",
                "activity": log_entry["activity"],
                "detail": detail_data,
            }
        )

    bulk_log_activity(bulk_entries)


def get_organization_name(org_id: str) -> str:
    """Get organization name from ID, with fallback."""
    try:
        from posthog.models.organization import Organization

        organization = Organization.objects.filter(id=org_id).first()
        if organization:
            return organization.name
    except Exception:
        pass
    return "Unknown Organization"


def get_team_name(team_id: Optional[int]) -> str:
    """Get team name from ID, with fallback."""
    try:
        team = Team.objects.filter(id=team_id).first()
        if team:
            return team.name
    except Exception:
        pass
    return "Unknown Project"


def log_personal_api_key_activity(api_key: PersonalAPIKey, activity: str, user, was_impersonated: bool, changes=None):
    """Create activity logs for PersonalAPIKey operations at appropriate organization/team levels."""
    access_locations = get_personal_api_key_access_locations(api_key)

    log_entries: list[LogActivityEntry] = []
    for location in access_locations:
        log_entries.append(
            {
                "organization_id": uuid.UUID(location.org_id),
                "team_id": location.team_id,
                "user": user,
                "was_impersonated": was_impersonated,
                "item_id": api_key.id,
                "scope": "PersonalAPIKey",
                "activity": activity,
                "detail": Detail(
                    changes=changes,
                    name=api_key.label,
                    context=PersonalAPIKeyContext(
                        user_id=api_key.user_id,
                        user_email=api_key.user.email,
                        user_name=api_key.user.get_full_name(),
                        organization_name=get_organization_name(location.org_id),
                        team_name=get_team_name(location.team_id),
                    ),
                ),
            }
        )

    bulk_log_activity(log_entries)
