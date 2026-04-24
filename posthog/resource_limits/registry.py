from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LimitDefinition:
    """A single entry in the resource limit catalog.

    Resource limits cap the count of durable, stored entities per team. They
    are distinct from billing usage quotas (which meter flow over a billing
    period and live under ``ee/billing/``). Resource limits have no plan
    linkage and no auto-approve ladder — when a customer hits one, staff
    manually grants an override via Django admin.
    """

    key: str
    description: str
    default: int | None
    unit: Literal["count", "bytes", "seconds"] = "count"


# The single source of truth for every resource limit. All limits are scoped
# to a team (environment); if staff want to apply the same bump across every
# team in an org, they grant a per-team override to each one.
REGISTRY: dict[str, LimitDefinition] = {
    "analytics.max_dashboards_per_team": LimitDefinition(
        key="analytics.max_dashboards_per_team",
        description="Maximum saved dashboards in a project",
        default=500,
    ),
    "analytics.max_insights_per_dashboard": LimitDefinition(
        key="analytics.max_insights_per_dashboard",
        description="Maximum insight tiles attached to a single dashboard",
        default=100,
    ),
    "analytics.max_alerts_per_team": LimitDefinition(
        key="analytics.max_alerts_per_team",
        description="Maximum alert configurations in a project",
        default=200,
    ),
    "analytics.max_subscriptions_per_team": LimitDefinition(
        key="analytics.max_subscriptions_per_team",
        description="Maximum scheduled subscriptions in a project",
        default=200,
    ),
    "analytics.max_actions_per_team": LimitDefinition(
        key="analytics.max_actions_per_team",
        description="Maximum saved actions in a project",
        default=500,
    ),
}


def get_definition(key: str) -> LimitDefinition:
    return REGISTRY[key]
