from typing import TYPE_CHECKING

from posthog.resource_limits.exceptions import LimitExceeded
from posthog.resource_limits.metrics import LIMIT_EXCEEDED_COUNTER
from posthog.resource_limits.registry import get_definition
from posthog.resource_limits.request_upsert import upsert_limit_increase_request

if TYPE_CHECKING:
    from posthog.models.organization_limit_override import OrganizationLimitOverride
    from posthog.models.team.team import Team
    from posthog.models.user import User


def _get_active_override(team: "Team", key: str) -> "OrganizationLimitOverride | None":
    from posthog.models.organization_limit_override import OrganizationLimitOverride

    return OrganizationLimitOverride.objects.filter(team_id=team.id, limit_key=key).first()


def get_limit(*, team: "Team", key: str) -> int | None:
    """Resolve the effective resource limit for a team/key.

    Precedence (highest first):
        1. Active per-team override in ``OrganizationLimitOverride``.
        2. Default from :data:`posthog.resource_limits.registry.REGISTRY`.

    Returns ``None`` to signal "unlimited".
    """
    override = _get_active_override(team, key)
    if override is not None:
        return override.value
    return get_definition(key).default


def check_count_limit(
    *,
    team: "Team",
    key: str,
    current_count: int,
    user: "User | None" = None,
) -> None:
    """Raise :class:`LimitExceeded` when the team is at-or-above the limit.

    On raise, upserts a pending :class:`~posthog.models.limit_increase_request.LimitIncreaseRequest`
    and increments the ``resource_limit_exceeded_total`` Prometheus counter.

    The check is ``>=`` (not ``>``) because the caller runs this immediately
    before creating a new entity — at ``current_count == limit`` the next
    create would push them over.
    """
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
    LIMIT_EXCEEDED_COUNTER.labels(
        limit_key=key,
        team_id=str(team.id),
    ).inc()
    raise LimitExceeded(
        limit_key=key,
        limit=limit,
        current=current_count,
        request_id=str(request.id),
    )
