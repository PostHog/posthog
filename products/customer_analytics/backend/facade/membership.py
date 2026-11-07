from posthog.models.team import Team

from products.customer_analytics.backend.logic.membership_backfill import (
    MembershipReadiness,
    get_membership_group_type_index,
    get_membership_readiness,
)

__all__ = ["get_membership_group_type_index", "get_membership_readiness", "is_membership_ready"]


def is_membership_ready(team: Team) -> bool:
    return get_membership_readiness(team) == MembershipReadiness.READY
