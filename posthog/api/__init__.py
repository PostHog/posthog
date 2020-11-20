from rest_framework import decorators, exceptions

from posthog.api.utils import DefaultRouterPlusPlus
from posthog.ee import is_ee_enabled

from . import (
    action,
    annotation,
    cohort,
    dashboard,
    element,
    event,
    feature_flag,
    funnel,
    insight,
    organization,
    organization_invite,
    organization_member,
    paths,
    person,
    personal_api_key,
    plugin,
    team,
)


@decorators.api_view(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@decorators.authentication_classes([])
@decorators.permission_classes([])
def api_not_found(request):
    raise exceptions.NotFound(detail="Endpoint not found.")


router = DefaultRouterPlusPlus()
# legacy endpoints (to be removed eventually)
router.register(r"annotation", annotation.LegacyAnnotationsViewSet)
router.register(r"feature_flag", feature_flag.LegacyFeatureFlagViewSet)
router.register(r"funnel", funnel.LegacyFunnelViewSet)
router.register(r"dashboard", dashboard.LegacyDashboardsViewSet)
router.register(r"dashboard_item", dashboard.LegacyDashboardItemsViewSet)
router.register(r"cohort", cohort.LegacyCohortViewSet)
router.register(
    r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys"
)  # TODO /users/:id/...
# nested endpoints
router.register(r"personal-api-keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
router.register(r"dashboards", dashboard.DashboardsViewSet, "shared_dashboards")
projects_router = router.register(r"projects", team.TeamViewSet)
projects_router.register(r"annotations", annotation.AnnotationsViewSet, "project_annotations", ["team_id"])
projects_router.register(r"feature-flags", feature_flag.FeatureFlagViewSet, "project_feature_flags", ["team_id"])
projects_router.register(r"funnels", funnel.FunnelViewSet, "project_funnels", ["team_id"])
projects_router.register(r"dashboards", dashboard.DashboardsViewSet, "project_dashboards", ["team_id"])
projects_router.register(r"dashboard-items", dashboard.DashboardItemsViewSet, "project_dashboard_items", ["team_id"])
projects_router.register(r"cohorts", cohort.CohortViewSet, "project_cohorts", ["team_id"])
router.register(r"plugins", plugin.PluginViewSet, "project_plugins")
projects_router.register(r"plugin-configs", plugin.PluginConfigViewSet, "project_plugin_configs", ["team_id"])
organizations_router = router.register(r"organizations", organization.OrganizationViewSet)
organizations_router.register(
    r"members", organization_member.OrganizationMemberViewSet, "organization_members", ["organization_id"],
)
organizations_router.register(
    r"invites", organization_invite.OrganizationInviteViewSet, "organization_invites", ["organization_id"],
)

if is_ee_enabled():
    try:
        from ee.clickhouse.views.actions import ClickhouseActionsViewSet, LegacyClickhouseActionsViewSet
        from ee.clickhouse.views.element import ClickhouseElementViewSet, LegacyClickhouseElementViewSet
        from ee.clickhouse.views.events import ClickhouseEventsViewSet, LegacyClickhouseEventsViewSet
        from ee.clickhouse.views.insights import ClickhouseInsightsViewSet, LegacyClickhouseInsightsViewSet
        from ee.clickhouse.views.paths import ClickhousePathsViewSet, LegacyClickhousePathsViewSet
        from ee.clickhouse.views.person import ClickhousePersonViewSet, LegacyClickhousePersonViewSet
    except ImportError as e:
        print("ClickHouse enabled but missing enterprise capabilities. Defaulting to Postgres.")
        print(e)
    else:
        # legacy endpoints (to be removed eventually)
        router.register(r"action", LegacyClickhouseActionsViewSet, basename="action")
        router.register(r"event", LegacyClickhouseEventsViewSet, basename="event")
        router.register(r"insight", LegacyClickhouseInsightsViewSet, basename="insight")
        router.register(r"person", LegacyClickhousePersonViewSet, basename="person")
        router.register(r"paths", LegacyClickhousePathsViewSet, basename="paths")
        router.register(r"element", LegacyClickhouseElementViewSet, basename="element")
        # nested endpoints
        projects_router.register(r"insights", ClickhouseInsightsViewSet, "project_insights", ["team_id"])
        projects_router.register(r"actions", ClickhouseActionsViewSet, "project_actions", ["team_id"])
        projects_router.register(r"persons", ClickhousePersonViewSet, "project_persons", ["team_id"])
        projects_router.register(r"events", ClickhouseEventsViewSet, "project_events", ["team_id"])
        projects_router.register(r"paths", ClickhousePathsViewSet, "project_paths", ["team_id"])
        projects_router.register(r"elements", ClickhouseElementViewSet, "project_elements", ["team_id"])
else:
    # legacy endpoints (to be removed eventually)
    router.register(r"insight", insight.InsightViewSet)
    router.register(r"action", action.ActionViewSet)
    router.register(r"person", person.PersonViewSet)
    router.register(r"event", event.EventViewSet)
    router.register(r"paths", paths.PathsViewSet, basename="paths")
    router.register(r"element", element.ElementViewSet)
    # nested endpoints
    projects_router.register(r"insights", insight.InsightViewSet, "project_insights", ["team_id"])
    projects_router.register(r"actions", action.ActionViewSet, "project_actions", ["team_id"])
    projects_router.register(r"persons", person.PersonViewSet, "project_persons", ["team_id"])
    projects_router.register(r"events", event.EventViewSet, "project_events", ["team_id"])
    projects_router.register(r"paths", paths.PathsViewSet, "project_paths", ["team_id"])
    projects_router.register(r"elements", element.ElementViewSet, "project_elements", ["team_id"])
