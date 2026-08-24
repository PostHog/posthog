from posthog.api.routing import RouterRegistry

from products.ai_gateway.backend.api import UserSpendLimitViewSet


def register_routes(routers: RouterRegistry) -> None:
    # Usage is read from events and a project secret key reaches the gateway
    # directly, so the only management resource here is a person's own limit.
    routers.projects.register(
        r"ai_gateway/@me/spend_limit",
        UserSpendLimitViewSet,
        "project_ai_gateway_user_spend_limit",
        ["team_id"],
    )
