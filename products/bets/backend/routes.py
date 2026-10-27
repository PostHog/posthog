from posthog.api.routing import RouterRegistry

from .presentation.views import BetsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"bets", BetsViewSet, "project_bets", ["project_id"])
