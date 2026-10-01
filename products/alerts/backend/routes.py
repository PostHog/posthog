from posthog.api.routing import RouterRegistry

import products.alerts.backend.presentation.views.alert as alert
import products.alerts.backend.presentation.views.platform_alert as platform_alert


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"alerts",
        alert.AlertViewSet,
        "project_alerts",
        ["team_id"],
    )
    routers.projects.register(
        r"platform_alerts",
        platform_alert.PlatformAlertConfigurationViewSet,
        "project_platform_alerts",
        ["team_id"],
    )
    # ThresholdViewSet is registered as a sub-route under insights/<id>/thresholds
    # by products.product_analytics.backend.routes — it imports alert.ThresholdViewSet.
