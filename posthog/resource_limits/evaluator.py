from typing import TYPE_CHECKING

from posthog.resource_limits.exceptions import LimitExceeded
from posthog.resource_limits.registry import get_definition
from posthog.resource_limits.request_upsert import upsert_limit_increase_request

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.team_limit_override import TeamLimitOverride
    from posthog.models.user import User


def _get_active_override(team: "Team", key: str) -> "TeamLimitOverride | None":
    from posthog.models.team_limit_override import TeamLimitOverride

    return TeamLimitOverride.objects.filter(team_id=team.id, limit_key=key).first()


def get_limit(*, team: "Team", key: str) -> int | None:
    """Resolve the effective resource limit for a team/key.

    The override acts as a floor. It can only raise the cap above the catalog
    default, never lower it. If the catalog default is later bumped above an
    approved override, the team still benefits from the raise (matches the
    usual "grant this team more headroom" intent so stale low overrides don't
    silently cap teams below everyone else).

    ``None`` signals "unlimited" on either side and wins over any finite value.
    """
    default = get_definition(key).default
    override = _get_active_override(team, key)
    if override is None:
        return default
    if override.value is None or default is None:
        return None
    return max(override.value, default)


def check_count_limit(
    *,
    team: "Team",
    key: str,
    current_count: int,
    user: "User | None" = None,
) -> None:
    """Raise :class:`LimitExceeded` when the team is at-or-above the limit.

    On raise, upserts a pending :class:`~posthog.models.limit_increase_request.LimitIncreaseRequest`
    and emits a ``resource limit hit`` PostHog event tagged with the team/org
    groups and the rich context staff need to triage the request.

    The check is ``>=`` (not ``>``) because the caller runs this immediately
    before creating a new entity — at ``current_count == limit`` the next
    create would push them over.
    """
    from posthog.event_usage import report_user_action

    limit = get_limit(team=team, key=key)
    if limit is None or current_count < limit:
        return

    request = upsert_limit_increase_request(
        team=team,
        limit_key=key,
        limit=limit,
        current_count=current_count,
        user=user,
    )

    if user is not None:
        report_user_action(
            user,
            "resource limit hit",
            {
                "limit_key": key,
                "limit": limit,
                "current_count": current_count,
                "team_id": team.id,
                "organization_id": str(team.organization_id),
                "limit_increase_request_id": str(request.id),
                "hit_count": request.hit_count,
            },
            team=team,
            organization=team.organization,
        )

    raise LimitExceeded(
        limit_key=key,
        limit=limit,
        current=current_count,
        request_id=str(request.id),
    )
