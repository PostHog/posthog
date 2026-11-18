from posthog.api.routing import RouterRegistry

import products.alerts_platform.backend.presentation.views.platform_alert as platform_alert
import products.alerts_platform.backend.presentation.views.platform_alert_routing as platform_alert_routing


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"platform_alerts",
        platform_alert.PlatformAlertConfigurationViewSet,
        "project_platform_alerts",
        ["team_id"],
    )
    routers.projects.register(
        r"platform_alert_receivers",
        platform_alert_routing.PlatformAlertReceiverViewSet,
        "project_platform_alert_receivers",
        ["team_id"],
    )
    routers.projects.register(
        r"platform_alert_routes",
        platform_alert_routing.PlatformAlertRouteViewSet,
        "project_platform_alert_routes",
        ["team_id"],
    )
