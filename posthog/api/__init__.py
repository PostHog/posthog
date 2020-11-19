from rest_framework import decorators, exceptions
from rest_framework_extensions.routers import ExtendedDefaultRouter

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


class DefaultRouterPlusPlus(ExtendedDefaultRouter):
    """DefaultRouter with optional trailing slash and drf-extensions nesting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = r"/?"


@decorators.api_view(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@decorators.authentication_classes([])
@decorators.permission_classes([])
def api_not_found(request):
    raise exceptions.NotFound(detail="Endpoint not found.")


router = DefaultRouterPlusPlus()
router.register(r"personal-api-keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
teams_router = router.register(r"projects", team.TeamViewSet)
teams_router.register(r"annotations", annotation.AnnotationsViewSet, "project_annotations", ["team_id"])
teams_router.register(r"feature-flags", feature_flag.FeatureFlagViewSet, "project_feature_flags", ["team_id"])
teams_router.register(r"funnels", funnel.FunnelViewSet, "project_funnels", ["team_id"])
teams_router.register(r"dashboards", dashboard.DashboardsViewSet, "project_dashboards", ["team_id"])
teams_router.register(r"dashboard-items", dashboard.DashboardItemsViewSet, "project_dashboard_items", ["team_id"])
teams_router.register(r"cohorts", cohort.CohortViewSet, "project_cohorts", ["team_id"])
router.register(r"plugins", plugin.PluginViewSet, "project_plugins")
teams_router.register(r"plugin-configs", plugin.PluginConfigViewSet, "project_plugin_configs", ["team_id"])
organizations_router = router.register(r"organizations", organization.OrganizationViewSet)
organizations_router.register(
    r"members", organization_member.OrganizationMemberViewSet, "organization_members", ["organization_id"],
)
organizations_router.register(
    r"invites", organization_invite.OrganizationInviteViewSet, "organization_invites", ["organization_id"],
)

if is_ee_enabled():
    try:
        from ee.clickhouse.views.actions import ClickhouseActions
        from ee.clickhouse.views.element import ClickhouseElement
        from ee.clickhouse.views.events import ClickhouseEvents
        from ee.clickhouse.views.insights import ClickhouseInsights
        from ee.clickhouse.views.paths import ClickhousePathsViewSet
        from ee.clickhouse.views.person import ClickhousePerson
    except ImportError as e:
        print("ClickHouse enabled but missing enterprise capabilities. Defaulting to Postgres.")
        print(e)
    else:
        teams_router.register(r"insights", ClickhouseInsights, "project_insights", ["team_id"])
        teams_router.register(r"actions", ClickhouseActions, "project_actions", ["team_id"])
        teams_router.register(r"persons", ClickhousePerson, "project_persons", ["team_id"])
        teams_router.register(r"events", ClickhouseEvents, "project_events", ["team_id"])
        teams_router.register(r"paths", ClickhousePathsViewSet, "project_paths", ["team_id"])
        teams_router.register(r"elements", ClickhouseElement, "project_elements", ["team_id"])
else:
    teams_router.register(r"insights", insight.InsightViewSet, "project_insights", ["team_id"])
    teams_router.register(r"actions", action.ActionViewSet, "project_actions", ["team_id"])
    teams_router.register(r"persons", person.PersonViewSet, "project_persons", ["team_id"])
    teams_router.register(r"events", event.EventViewSet, "project_events", ["team_id"])
    teams_router.register(r"paths", paths.PathsViewSet, "project_paths", ["team_id"])
    teams_router.register(r"elements", element.ElementViewSet, "project_elements", ["team_id"])
