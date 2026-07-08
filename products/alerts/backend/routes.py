from posthog.api.routing import RouterRegistry

import products.alerts.backend.api.alert as alert


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(
        r"alerts",
        alert.AlertViewSet,
        "environment_alerts",
        ["team_id"],
    )
    # ThresholdViewSet is registered as a sub-route under insights/<id>/thresholds
    # by products.product_analytics.backend.routes — it imports alert.ThresholdViewSet.
