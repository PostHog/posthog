from posthog.api.routing import RouterRegistry

import products.alerts.backend.presentation.views.alert as alert


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"alerts",
        alert.AlertViewSet,
        "project_alerts",
        ["team_id"],
    )
