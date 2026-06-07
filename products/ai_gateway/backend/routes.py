from posthog.api.routing import RouterRegistry

from products.ai_gateway.backend.api import GatewayViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"gateways", GatewayViewSet, "project_gateways", ["team_id"])
