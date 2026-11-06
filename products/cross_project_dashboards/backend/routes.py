from posthog.api.routing import RouterRegistry

from products.cross_project_dashboards.backend.presentation.views import (
    CrossProjectDashboardTileViewSet,
    CrossProjectDashboardViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    dashboards_router = routers.organizations.register(
        r"cross_project_dashboards",
        CrossProjectDashboardViewSet,
        "organization_cross_project_dashboards",
        ["organization_id"],
    )
    # Tiles are edited one at a time so concurrent editors cannot overwrite each other.
    dashboards_router.register(
        r"tiles",
        CrossProjectDashboardTileViewSet,
        "organization_cross_project_dashboard_tiles",
        ["organization_id", "dashboard_id"],
    )
