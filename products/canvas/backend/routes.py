from posthog.api.routing import RouterRegistry

from products.canvas.backend.presentation import views


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"canvases", views.CanvasViewSet, "project_canvases", ["team_id"])
    routers.projects.register(r"canvas_boards", views.CanvasBoardViewSet, "project_canvas_boards", ["team_id"])
