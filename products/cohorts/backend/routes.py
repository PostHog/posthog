from posthog.api.routing import RouterRegistry

from products.cohorts.backend.api import staff_tools


def register_routes(routers: RouterRegistry) -> None:
    # Staff-only, unscoped cohorts tooling: root-level so it is not team-nested.
    routers.root.register(r"cohorts_staff", staff_tools.CohortsStaffToolsViewSet, "cohorts_staff")
