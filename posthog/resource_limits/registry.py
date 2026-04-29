from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LimitDefinition:
    """A single entry in the resource limit catalog.

    Each entry names a per-team resource we watch. When a team is about to
    create a resource that would put them at or above ``default``, the
    evaluator emits a ``resource limit hit`` PostHog event so ops can route
    via Action and Slack destination. The create itself is not blocked.
    """

    key: str
    description: str
    default: int | None
    unit: Literal["count", "bytes", "seconds"] = "count"


REGISTRY: dict[str, LimitDefinition] = {
    "analytics.max_dashboards_per_team": LimitDefinition(
        key="analytics.max_dashboards_per_team",
        description="Saved dashboards in a project",
        default=500,
    ),
    "analytics.max_insights_per_dashboard": LimitDefinition(
        key="analytics.max_insights_per_dashboard",
        description="Insight tiles attached to a single dashboard",
        default=100,
    ),
    "analytics.max_alerts_per_team": LimitDefinition(
        key="analytics.max_alerts_per_team",
        description="Alert configurations in a project",
        default=200,
    ),
    "analytics.max_subscriptions_per_team": LimitDefinition(
        key="analytics.max_subscriptions_per_team",
        description="Scheduled subscriptions in a project",
        default=200,
    ),
    "analytics.max_actions_per_team": LimitDefinition(
        key="analytics.max_actions_per_team",
        description="Saved actions in a project",
        default=500,
    ),
}


def get_definition(key: str) -> LimitDefinition:
    return REGISTRY[key]
