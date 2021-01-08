from rest_framework import decorators, exceptions

from posthog.api.routing import DefaultRouterPlusPlus
from posthog.ee import is_ee_enabled

from . import (
    action,
    annotation,
    cohort,
    dashboard,
    element,
    event,
    feature_flag,
    insight,
    organization,
    organization_invite,
    organization_member,
    paths,
    person,
    personal_api_key,
    plugin,
    sessions_filter,
    team,
)


@decorators.api_view(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@decorators.authentication_classes([])
@decorators.permission_classes([])
def api_not_found(request):
    raise exceptions.NotFound(detail="Endpoint not found.")


router = DefaultRouterPlusPlus()
# legacy endpoints (to be removed eventually)
router.register(r"annotation", annotation.AnnotationsViewSet)
router.register(r"feature_flag", feature_flag.FeatureFlagViewSet)
router.register(r"dashboard", dashboard.DashboardsViewSet)
router.register(r"dashboard_item", dashboard.DashboardItemsViewSet)
router.register(r"cohort", cohort.CohortViewSet)
router.register(r"plugin_config", plugin.PluginConfigViewSet)
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
router.register(r"sessions_filter", sessions_filter.SessionsFilterViewSet)
# nested endpoints
projects_router = router.register(r"projects", team.TeamViewSet)
organizations_router = router.register(r"organizations", organization.OrganizationViewSet)
organizations_router.register(r"plugins", plugin.PluginViewSet, "organization_plugins", ["organization_id"])
organizations_router.register(
    r"members", organization_member.OrganizationMemberViewSet, "organization_members", ["organization_id"],
)
organizations_router.register(
    r"invites", organization_invite.OrganizationInviteViewSet, "organization_invites", ["organization_id"],
)

if is_ee_enabled():
    try:
        from ee.clickhouse.views.actions import ClickhouseActionsViewSet, LegacyClickhouseActionsViewSet
        from ee.clickhouse.views.element import ClickhouseElementViewSet
        from ee.clickhouse.views.events import ClickhouseEventsViewSet
        from ee.clickhouse.views.insights import ClickhouseInsightsViewSet
        from ee.clickhouse.views.paths import ClickhousePathsViewSet
        from ee.clickhouse.views.person import ClickhousePersonViewSet
    except ImportError as e:
        print("ClickHouse enabled but missing enterprise capabilities. Defaulting to Postgres.")
        print(e)
    else:
        # legacy endpoints (to be removed eventually)
        router.register(r"action", LegacyClickhouseActionsViewSet, basename="action")
        router.register(r"event", ClickhouseEventsViewSet, basename="event")
        router.register(r"insight", ClickhouseInsightsViewSet, basename="insight")
        router.register(r"person", ClickhousePersonViewSet, basename="person")
        router.register(r"paths", ClickhousePathsViewSet, basename="paths")
        router.register(r"element", ClickhouseElementViewSet, basename="element")
        # nested endpoints
        projects_router.register(r"actions", ClickhouseActionsViewSet, "project_actions", ["team_id"])
else:
    # legacy endpoints (to be removed eventually)
    router.register(r"insight", insight.InsightViewSet)
    router.register(r"action", action.LegacyActionViewSet)
    router.register(r"person", person.PersonViewSet)
    router.register(r"event", event.EventViewSet)
    router.register(r"paths", paths.PathsViewSet, basename="paths")
    router.register(r"element", element.ElementViewSet)
    # nested endpoints
    projects_router.register(r"actions", action.ActionViewSet, "project_actions", ["team_id"])
