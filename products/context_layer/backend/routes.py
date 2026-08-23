from posthog.api.routing import RouterRegistry

from products.context_layer.backend.presentation.views import ContextLayerAgentViewSet, ContextLayerViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.organizations.register(
        r"context_layer", ContextLayerViewSet, "organization_context_layer", ["organization_id"]
    )
    # A sandbox run token carries `scoped_teams`, which APIScopePermission accepts
    # only on a project-nested route, so agents reach the same wiki here.
    routers.projects.register(r"context_layer", ContextLayerAgentViewSet, "project_context_layer", ["team_id"])
