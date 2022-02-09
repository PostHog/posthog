from typing import Any, List

from django.urls.conf import path
from rest_framework_extensions.routers import NestedRegistryItem

from posthog.api.routing import DefaultRouterPlusPlus

from .api import authentication, dashboard_collaborator, debug_ch_queries, explicit_team_member, hooks, license


def extend_api_router(
    root_router: DefaultRouterPlusPlus,
    *,
    projects_router: NestedRegistryItem,
    project_dashboards_router: NestedRegistryItem
) -> None:
    root_router.register(r"license", license.LicenseViewSet)
    root_router.register(r"debug_ch_queries", debug_ch_queries.DebugCHQueries, "debug_ch_queries")
    projects_router.register(r"hooks", hooks.HookViewSet, "project_hooks", ["team_id"])
    projects_router.register(
        r"explicit_members", explicit_team_member.ExplicitTeamMemberViewSet, "project_explicit_members", ["team_id"]
    )
    project_dashboards_router.register(
        r"collaborators",
        dashboard_collaborator.DashboardCollaboratorViewSet,
        "project_dashboard_collaborators",
        ["team_id", "dashboard_id"],
    )


urlpatterns: List[Any] = [
    path("api/saml/metadata/", authentication.saml_metadata_view),
]
