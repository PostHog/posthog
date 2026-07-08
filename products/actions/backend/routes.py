from posthog.api.routing import RouterRegistry

from products.actions.backend.api.action import ActionViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"actions", ActionViewSet, "project_actions", ["project_id"])
