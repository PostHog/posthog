from posthog.api.routing import RouterRegistry

from products.canvas.backend.presentation import views
from products.canvas.backend.presentation.sketchpad import views as sketchpad_views


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"canvases", views.CanvasViewSet, "project_canvases", ["team_id"])
    routers.projects.register(r"sketchpads", sketchpad_views.SketchpadViewSet, "project_sketchpads", ["team_id"])
