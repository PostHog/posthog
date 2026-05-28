from typing import TYPE_CHECKING

from posthog.event_usage import report_user_action
from posthog.resource_limits.registry import get_definition

if TYPE_CHECKING:
    from posthog.models.organization import Organization
    from posthog.models.team.team import Team
    from posthog.models.user import User


def get_limit(*, team: "Team", key: str) -> int | None:
    return get_definition(key).default


def get_organization_limit(*, organization: "Organization", key: str) -> int | None:
    """Resolve a tiered limit for an organization, falling back to ``default``.

    For limits with ``by_plan_tier`` set, returns the value matching the
    organization's plan tier from ``Organization.get_plan_tier()``. For
    limits without tier overrides, returns ``default`` unchanged.
    """
    definition = get_definition(key)
    if definition.by_plan_tier is None:
        return definition.default
    tier = organization.get_plan_tier()
    return definition.by_plan_tier.get(tier, definition.default)


def check_count_limit(
    *,
    team: "Team",
    key: str,
    current_count: int,
    user: "User | None" = None,
) -> None:
    """Emit a ``resource limit hit`` PostHog event when a team's next create
    would put them at or above the catalog threshold for ``key``.

    The caller passes ``current_count`` as the count of existing rows just
    before creating the next one, so the create would land the team at
    ``current_count + 1``. The event is emitted whenever that value reaches
    or exceeds the threshold; ``crossing_threshold`` flags the exact moment
    the team crosses for the first time so a downstream PostHog Action can
    pick stream vs one-shot semantics via property filter.

    Notification-only: this never raises ``LimitExceeded`` and never blocks
    the caller. The surrounding viewset proceeds with the create as usual.
    """
    limit = get_limit(team=team, key=key)
    if limit is None or current_count + 1 < limit:
        return

    if user is not None:
        report_user_action(
            user,
            "resource limit hit",
            {
                "limit_key": key,
                "limit": limit,
                "current_count": current_count,
                "crossing_threshold": current_count + 1 == limit,
                "team_id": team.id,
                "organization_id": str(team.organization_id),
            },
            team=team,
            organization=team.organization,
        )
