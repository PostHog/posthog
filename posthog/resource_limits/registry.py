from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

PlanTier = Literal["free", "paid", "enterprise"]


class LimitKey(StrEnum):
    """Stable string identifiers for every entry in the catalog. Use these
    at every call site to avoid typo'd lookups."""

    MAX_DASHBOARDS_PER_TEAM = "analytics.max_dashboards_per_team"
    MAX_INSIGHTS_PER_DASHBOARD = "analytics.max_insights_per_dashboard"
    MAX_ALERTS_PER_TEAM = "analytics.max_alerts_per_team"
    MAX_SUBSCRIPTIONS_PER_TEAM = "analytics.max_subscriptions_per_team"
    MAX_ACTIONS_PER_TEAM = "analytics.max_actions_per_team"
    MAX_ACTIVE_AI_SUMMARIES_PER_ORG = "subscriptions.max_active_ai_summaries_per_org"


@dataclass(frozen=True)
class LimitDefinition:
    """A single entry in the resource limit catalog.

    Each entry names a resource we watch. When a team is about to
    create a resource that would put them at or above ``default``, the
    evaluator emits a ``resource limit hit`` event. The create itself is
    not blocked.

    ``by_plan_tier`` carries optional tier-keyed overrides for limits that
    scale with billing plan. When set, callers should resolve the tier via
    the organization helper rather than reading ``default`` directly.
    Boost and Scale collapse to "paid" because PostHog's existing tier
    helper conflates them; revisit if/when the helper learns finer
    granularity.
    """

    key: str
    description: str
    default: int | None
    unit: Literal["count", "bytes", "seconds"] = "count"
    by_plan_tier: dict[PlanTier, int] | None = field(default=None)


REGISTRY: dict[str, LimitDefinition] = {
    LimitKey.MAX_DASHBOARDS_PER_TEAM: LimitDefinition(
        key=LimitKey.MAX_DASHBOARDS_PER_TEAM,
        description="Saved dashboards in a project",
        default=5000,
    ),
    LimitKey.MAX_INSIGHTS_PER_DASHBOARD: LimitDefinition(
        key=LimitKey.MAX_INSIGHTS_PER_DASHBOARD,
        description="Insight tiles attached to a single dashboard",
        default=100,
    ),
    LimitKey.MAX_ALERTS_PER_TEAM: LimitDefinition(
        key=LimitKey.MAX_ALERTS_PER_TEAM,
        description="Alert configurations in a project",
        default=200,
    ),
    LimitKey.MAX_SUBSCRIPTIONS_PER_TEAM: LimitDefinition(
        key=LimitKey.MAX_SUBSCRIPTIONS_PER_TEAM,
        description="Scheduled subscriptions in a project",
        default=200,
    ),
    LimitKey.MAX_ACTIONS_PER_TEAM: LimitDefinition(
        key=LimitKey.MAX_ACTIONS_PER_TEAM,
        description="Saved actions in a project",
        default=500,
    ),
    LimitKey.MAX_ACTIVE_AI_SUMMARIES_PER_ORG: LimitDefinition(
        key=LimitKey.MAX_ACTIVE_AI_SUMMARIES_PER_ORG,
        description="Subscriptions with summary_enabled=True per organization",
        default=20,
        by_plan_tier={"free": 20, "paid": 40, "enterprise": 200},
    ),
}


def get_definition(key: str) -> LimitDefinition:
    return REGISTRY[key]
