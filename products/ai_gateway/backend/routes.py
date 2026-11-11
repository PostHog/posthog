from posthog.api.routing import RouterRegistry

from .presentation.views import DevGatewayTokenViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"ai_gateway/dev_tokens", DevGatewayTokenViewSet, "ai_gateway_dev_tokens")
