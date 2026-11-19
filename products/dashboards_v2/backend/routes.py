from posthog.api.routing import RouterRegistry

from products.dashboards_v2.backend.presentation.views import DashboardV2ViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"dashboards_v2", DashboardV2ViewSet, "project_dashboards_v2", ["team_id"])
