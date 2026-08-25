from posthog.api.routing import RouterRegistry

from products.ai_gateway.backend.presentation.views import UserSpendLimitViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"ai_gateway/@me/spend_limit",
        UserSpendLimitViewSet,
        "project_ai_gateway_user_spend_limit",
        ["team_id"],
    )
