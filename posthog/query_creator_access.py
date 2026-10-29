from typing import Any, Optional

from django.db.models import Model

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.ph_client import ph_scoped_capture

from products.access_control.backend.facade.user_access_control import (
    UserAccessControl,
    UserAccessControlError,
    model_to_resource,
)


class CreatorLeftOrganizationError(Exception):
    """A background query refused to run because its owner can no longer access the project."""

    def __init__(self) -> None:
        super().__init__("The owner no longer has access to this project.")


def creator_access_revoked(user: Optional[User], team: Team) -> bool:
    """True when `user` no longer has access to `team`: they were deleted (`user is None`),
    deactivated, left the team's org, or lost access to the project.
    """
    if user is None:
        return True
    if not user.is_active:
        return True
    if not OrganizationMembership.objects.filter(organization_id=team.organization_id, user=user).exists():
        return True
    return not team.all_users_with_access(user_uuids=[str(user.uuid)]).filter(id=user.id).exists()


def assert_creator_can_view(user: User, team: Team, *objects: Model | None) -> None:
    """Raise `UserAccessControlError` for the first of `objects` that `user` can no longer view.

    Background jobs load their dashboard and insight directly, so nothing else checks object access
    for them. Organization admins pass, and a `None` object is skipped.
    """
    user_access_control = UserAccessControl(user=user, team=team)
    for obj in objects:
        if obj is None or user_access_control.check_access_level_for_object(obj, "viewer"):
            continue
        resource = model_to_resource(obj)
        if resource is None:
            continue
        raise UserAccessControlError(resource, "viewer", str(obj.pk))


def report_creator_access_revoked(
    *,
    user: Optional[User],
    team: Team,
    source: str,
    error: BaseException,
    properties: Optional[dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> None:
    """Record an analytics event for a background query that failed because its creator lost access
    (see `creator_access_revoked`). Attributed to the team — the creator may be gone or anonymous.
    `source` names the caller ("export", "alert", "cache_warming"). Pass `reason` when the creator is
    still a member but has no access to a resource the query needs.
    """
    if reason is None:
        reason = "deleted" if user is None else "deactivated" if not user.is_active else "left_org"
    # Attributed to the team — the creator may be deleted or anonymous.
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(team.uuid),
            # Name of the PostHog analytics event we emit - not an error or log message.
            event="background query creator access revoked",
            properties={
                "source": source,
                "reason": reason,
                "team_id": team.id,
                "organization_id": str(team.organization_id),
                "creator_user_id": user.id if user else None,
                "error": str(error),
                **(properties or {}),
            },
        )
