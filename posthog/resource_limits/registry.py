from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class LimitKey(StrEnum):
    """Stable string identifiers for every entry in the catalog. Use these
    at every call site to avoid typo'd lookups."""

    MAX_DASHBOARDS_PER_TEAM = "analytics.max_dashboards_per_team"
    MAX_INSIGHTS_PER_DASHBOARD = "analytics.max_insights_per_dashboard"
    MAX_ALERTS_PER_TEAM = "analytics.max_alerts_per_team"
    MAX_SUBSCRIPTIONS_PER_TEAM = "analytics.max_subscriptions_per_team"
    MAX_ACTIONS_PER_TEAM = "analytics.max_actions_per_team"


@dataclass(frozen=True)
class LimitDefinition:
    """A single entry in the resource limit catalog.

    Each entry names a per-team resource we watch. When a team is about to
    create a resource that would put them at or above ``default``, the
    evaluator emits a ``resource limit hit`` event. The create itself is
    not blocked.
    """

    key: str
    description: str
    default: int | None
    unit: Literal["count", "bytes", "seconds"] = "count"


REGISTRY: dict[str, LimitDefinition] = {
    LimitKey.MAX_DASHBOARDS_PER_TEAM: LimitDefinition(
        key=LimitKey.MAX_DASHBOARDS_PER_TEAM,
        description="Saved dashboards in a project",
        default=500,
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
}


def get_definition(key: str) -> LimitDefinition:
    return REGISTRY[key]
