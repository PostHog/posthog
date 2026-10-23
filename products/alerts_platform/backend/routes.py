from posthog.api.routing import RouterRegistry

import products.alerts_platform.backend.presentation.views.platform_alert as platform_alert


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"platform_alerts",
        platform_alert.PlatformAlertConfigurationViewSet,
        "project_platform_alerts",
        ["team_id"],
    )
