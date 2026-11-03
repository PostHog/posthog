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
    """A background query refused to run because its owner is no longer in the organization."""

    def __init__(self) -> None:
        super().__init__("The owner is no longer in the organization.")


def creator_access_revoked(user: Optional[User], team: Team) -> bool:
    """True when `user` no longer has access to `team`: they were deleted (`user is None`),
    deactivated, or are no longer a member of the team's org.
    """
    if user is None:
        return True
    if not user.is_active:
        return True
    return not OrganizationMembership.objects.filter(organization_id=team.organization_id, user=user).exists()


def assert_creator_can_run(user: Optional[User], team: Team, *objects: Model | None) -> None:
    """Raise when `user` can no longer run a background query for `team` as its owner.

    `CreatorLeftOrganizationError` when they were deleted (`user is None`), deactivated, or left the
    team's org. `UserAccessControlError` when they are still in the org but cannot view the project
    or one of `objects`. Background jobs load their dashboard and insight directly, so nothing else
    checks object access for them. Organization admins pass, and a `None` object is skipped.
    """
    if user is None or creator_access_revoked(user, team):
        raise CreatorLeftOrganizationError()
    user_access_control = UserAccessControl(user=user, team=team)
    # Object rules do not consult the project, so a member shut out of a private project is checked first.
    if not user_access_control.has_project_access:
        raise UserAccessControlError("project", "viewer", str(team.pk))
    for obj in objects:
        if obj is None:
            continue
        resource = model_to_resource(obj)
        # A model with no scope has no access rules, so there is nothing to deny.
        if resource is not None and not user_access_control.check_access_level_for_object(obj, "viewer"):
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
