from posthog.api.routing import RouterRegistry

from products.context_layer.backend.presentation.views import ContextLayerViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.organizations.register(
        r"context_layer", ContextLayerViewSet, "organization_context_layer", ["organization_id"]
    )
