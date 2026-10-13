from posthog.api.routing import RouterRegistry

from products.context_layer.backend.presentation.views import ContextLayerAgentViewSet, ContextLayerViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.organizations.register(
        r"context_layer", ContextLayerViewSet, "organization_context_layer", ["organization_id"]
    )
    # A run token carries `scoped_teams`, which APIScopePermission accepts only on a
    # project-nested route, so runs reach the same wiki here. The `/agent` segment
    # keeps this path's suffix distinct from the organization one above: an org path
    # whose suffix matches a project path is treated as a legacy alias and gets
    # deprecated, which would retire the human route and take its operation ids.
    routers.projects.register(r"context_layer/agent", ContextLayerAgentViewSet, "project_context_layer", ["team_id"])
