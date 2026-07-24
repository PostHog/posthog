from posthog.api.routing import RouterRegistry

import products.alerts.backend.api.alert as alert


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"alerts",
        alert.AlertViewSet,
        "project_alerts",
        ["team_id"],
    )
    # ThresholdViewSet is registered as a sub-route under insights/<id>/thresholds
    # by products.product_analytics.backend.routes — it imports alert.ThresholdViewSet.
