from posthog.api.routing import RouterRegistry

from products.analytics_platform.backend.api.precompute_debug import PrecomputeDebugViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"precompute_debug",
        PrecomputeDebugViewSet,
        "project_precompute_debug",
        ["team_id"],
    )
