from rest_framework import decorators, exceptions

from posthog.api.routing import DefaultRouterPlusPlus
from posthog.utils import is_clickhouse_enabled

from . import (
    action,
    annotation,
    authentication,
    cohort,
    dashboard,
    element,
    event,
    event_definition,
    feature_flag,
    insight,
    instance_status,
    organization,
    organization_invite,
    organization_member,
    paths,
    person,
    personal_api_key,
    plugin,
    plugin_log_entry,
    property_definition,
    session_recording,
    sessions_filter,
    team,
    user,
)


@decorators.api_view(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@decorators.authentication_classes([])
@decorators.permission_classes([])
def api_not_found(request):
    raise exceptions.NotFound(detail="Endpoint not found.")


router = DefaultRouterPlusPlus()

# Legacy endpoints (to be removed eventually)
router.register(r"annotation", annotation.AnnotationsViewSet)
router.register(r"feature_flag", feature_flag.FeatureFlagViewSet)
router.register(r"dashboard", dashboard.DashboardsViewSet)
router.register(r"dashboard_item", dashboard.DashboardItemsViewSet)
router.register(r"plugin_config", plugin.PluginConfigViewSet)
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
router.register(r"sessions_filter", sessions_filter.SessionsFilterViewSet)

# Nested endpoints
projects_router = router.register(r"projects", team.TeamViewSet)
project_plugins_configs_router = projects_router.register(
    r"plugin-configs", plugin.PluginConfigViewSet, "project_plugins_configs", ["team_id", "plugin_config_id"]
)
project_plugins_configs_router.register(
    r"logs", plugin_log_entry.PluginLogEntryViewSet, "project_plugins_config_logs", ["team_id", "plugin_config_id"]
)
projects_router.register(
    r"feature_flag_overrides", feature_flag.FeatureFlagOverrideViewset, "project_feature_flag_overrides", ["team_id"]
)

organizations_router = router.register(r"organizations", organization.OrganizationViewSet, "organizations")
organization_plugins_router = organizations_router.register(
    r"plugins", plugin.PluginViewSet, "organization_plugins", ["organization_id"]
)
organizations_router.register(
    r"members", organization_member.OrganizationMemberViewSet, "organization_members", ["organization_id"],
)
organizations_router.register(
    r"invites", organization_invite.OrganizationInviteViewSet, "organization_invites", ["organization_id"],
)
organizations_router.register(
    r"onboarding", organization.OrganizationOnboardingViewset, "organization_onboarding", ["organization_id"],
)

# Project nested endpoints
projects_router = router.register(r"projects", team.TeamViewSet, "projects")

projects_router.register(
    r"event_definitions", event_definition.EventDefinitionViewSet, "project_event_definitions", ["team_id"],
)
projects_router.register(
    r"property_definitions", property_definition.PropertyDefinitionViewSet, "project_property_definitions", ["team_id"],
)


# General endpoints (shared across EE & FOSS)
router.register(r"login", authentication.LoginViewSet)
router.register(r"users", user.UserViewSet)
router.register(r"instance_status", instance_status.InstanceStatusViewSet, "instance_status")

if is_clickhouse_enabled():
    try:
        from ee.clickhouse.views.actions import ClickhouseActionsViewSet, LegacyClickhouseActionsViewSet
        from ee.clickhouse.views.cohort import ClickhouseCohortViewSet
        from ee.clickhouse.views.element import ClickhouseElementViewSet
        from ee.clickhouse.views.events import ClickhouseEventsViewSet
        from ee.clickhouse.views.insights import ClickhouseInsightsViewSet
        from ee.clickhouse.views.paths import ClickhousePathsViewSet
        from ee.clickhouse.views.person import ClickhousePersonViewSet
        from ee.clickhouse.views.session_recordings import ClickhouseSessionRecordingViewSet
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
        router.register(r"cohort", ClickhouseCohortViewSet, basename="cohort")
        # nested endpoints
        projects_router.register(r"actions", ClickhouseActionsViewSet, "project_actions", ["team_id"])
        projects_router.register(
            r"session_recordings", ClickhouseSessionRecordingViewSet, "project_session_recordings", ["team_id"],
        )
else:
    # legacy endpoints (to be removed eventually)
    router.register(r"insight", insight.InsightViewSet)
    router.register(r"action", action.LegacyActionViewSet)
    router.register(r"person", person.PersonViewSet)
    router.register(r"event", event.EventViewSet)
    router.register(r"paths", paths.PathsViewSet, basename="paths")
    router.register(r"element", element.ElementViewSet)
    router.register(r"cohort", cohort.CohortViewSet)
    # nested endpoints
    projects_router.register(r"actions", action.ActionViewSet, "project_actions", ["team_id"])
    projects_router.register(
        r"session_recordings", session_recording.SessionRecordingViewSet, "project_session_recordings", ["team_id"],
    )
