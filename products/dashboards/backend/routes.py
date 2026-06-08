from posthog.api import sharing
from posthog.api.routing import RouterRegistry
from posthog.settings import EE_AVAILABLE

from products.dashboards.backend.api import dashboard, dashboard_templates


def register_routes(routers: RouterRegistry) -> None:
    # Legacy flat endpoints — should be unused, but kept until callers are confirmed dead.
    routers.root.register(r"dashboard", dashboard.LegacyDashboardsViewSet, "legacy_dashboards")
    routers.root.register(r"dashboard_item", dashboard.LegacyInsightViewSet, "legacy_insights")

    routers.projects.register(
        r"dashboard_templates",
        dashboard_templates.DashboardTemplateViewSet,
        "project_dashboard_templates",
        ["project_id"],
    )

    legacy_project_dashboards_router, environment_dashboards_router = routers.register_legacy_dual_route(
        r"dashboards", dashboard.DashboardsViewSet, "environment_dashboards", ["team_id"]
    )

    # SharingConfigurationViewSet is shared (core), but the route lives under
    # dashboards/<id>/sharing — the dashboards product owns the sub-route.
    environment_dashboards_router.register(
        r"sharing",
        sharing.SharingConfigurationViewSet,
        "environment_dashboard_sharing",
        ["team_id", "dashboard_id"],
    )
    legacy_project_dashboards_router.register(
        r"sharing",
        sharing.SharingConfigurationViewSet,
        "project_dashboard_sharing",
        ["team_id", "dashboard_id"],
    )

    # EE-only collaborator sub-route. Previously registered in ee/urls.py against
    # the (now product-local) dashboards routers — co-locating it here removes
    # ee/urls.py's coupling to dashboards' router handles.
    if EE_AVAILABLE:
        from ee.api import dashboard_collaborator

        environment_dashboards_router.register(
            r"collaborators",
            dashboard_collaborator.DashboardCollaboratorViewSet,
            "environment_dashboard_collaborators",
            ["project_id", "dashboard_id"],
        )
        legacy_project_dashboards_router.register(
            r"collaborators",
            dashboard_collaborator.DashboardCollaboratorViewSet,
            "project_dashboard_collaborators",
            ["project_id", "dashboard_id"],
        )
