from typing import Any, Optional

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.ph_client import ph_scoped_capture


def creator_access_revoked(user: Optional[User], team: Team) -> bool:
    """True when `user` no longer has access to `team`: they were deleted (`user is None`),
    deactivated, or are no longer a member of the team's org.
    """
    if user is None:
        return True
    if not user.is_active:
        return True
    return not OrganizationMembership.objects.filter(organization_id=team.organization_id, user=user).exists()


def report_creator_access_revoked(
    *,
    user: Optional[User],
    team: Team,
    source: str,
    error: BaseException,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """Record an analytics event for a background query that failed because its creator lost access
    (see `creator_access_revoked`). Attributed to the team — the creator may be gone or anonymous.
    `source` names the caller ("export", "alert", "cache_warming").
    """
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
