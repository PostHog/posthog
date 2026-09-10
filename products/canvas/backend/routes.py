from posthog.api.routing import RouterRegistry

from products.canvas.backend.presentation import views


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"canvases", views.CanvasViewSet, "project_canvases", ["team_id"])
