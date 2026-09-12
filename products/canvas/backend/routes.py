from posthog.api import sharing
from posthog.api.routing import RouterRegistry

from products.canvas.backend.presentation import views


def register_routes(routers: RouterRegistry) -> None:
    project_canvases_router = routers.projects.register(
        r"canvases", views.CanvasViewSet, "project_canvases", ["team_id"]
    )
    # The sharing viewset is core, but the sub-route lives under canvases/<id>/sharing.
    project_canvases_router.register(
        r"sharing",
        sharing.SharingConfigurationViewSet,
        "project_canvas_sharing",
        ["team_id", "canvas_id"],
    )
