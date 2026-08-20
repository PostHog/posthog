from posthog.api.routing import RouterRegistry

from products.canvas.backend.presentation import location_views, views


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"canvases", views.CanvasViewSet, "project_canvases", ["team_id"])
    # Root-level, because the caller is asking which project a canvas belongs to and so cannot
    # supply one. Every denial is a 404, so this cannot enumerate canvases.
    routers.root.register(r"canvas_locations", location_views.CanvasLocationViewSet, "canvas_locations")
