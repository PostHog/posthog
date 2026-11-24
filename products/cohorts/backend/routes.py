from posthog.api.routing import RouterRegistry

from products.cohorts.backend.api import staff_tools
from products.cohorts.backend.presentation import realtime_access


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"realtime_cohorts", realtime_access.RealtimeCohortsViewSet, "project_realtime_cohorts", ["team_id"]
    )
    # Staff-only, unscoped cohorts tooling: root-level so it is not team-nested.
    routers.root.register(r"cohorts_staff", staff_tools.CohortsStaffToolsViewSet, "cohorts_staff")
