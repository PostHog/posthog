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

# Legacy endpoints shared (to be removed eventually)
router.register(r"annotation", annotation.LegacyAnnotationsViewSet)
router.register(r"feature_flag", feature_flag.LegacyFeatureFlagViewSet)
router.register(r"dashboard", dashboard.LegacyDashboardsViewSet)
router.register(r"dashboard_item", dashboard.LegacyDashboardItemsViewSet)
router.register(r"plugin_config", plugin.LegacyPluginConfigViewSet)
router.register(r"sessions_filter", sessions_filter.LegacySessionsFilterViewSet)

# Nested endpoints shared
projects_router = router.register(r"projects", team.TeamViewSet)
project_plugins_configs_router = projects_router.register(
    r"plugin_configs", plugin.PluginConfigViewSet, "project_plugin_configs", ["team_id"]
)
project_plugins_configs_router.register(
    r"logs", plugin_log_entry.PluginLogEntryViewSet, "project_plugins_config_logs", ["team_id", "plugin_config_id"]
)
projects_router.register(
    r"feature_flag_overrides", feature_flag.FeatureFlagOverrideViewset, "project_feature_flag_overrides", ["team_id"]
)
projects_router.register(r"annotations", annotation.AnnotationsViewSet, "project_annotations", ["team_id"])
projects_router.register(r"feature_flags", feature_flag.FeatureFlagViewSet, "project_feature_flags", ["team_id"])
projects_router.register(r"dashboards", dashboard.DashboardsViewSet, "project_dashboards", ["team_id"])
projects_router.register(r"dashboard_items", dashboard.DashboardItemsViewSet, "project_dashboard_items", ["team_id"])
projects_router.register(
    r"sessions_filters", sessions_filter.SessionsFilterViewSet, "project_session_filters", ["team_id"]
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


# General endpoints (shared across CH & PG)
router.register(r"login", authentication.LoginViewSet)
router.register(r"users", user.UserViewSet)
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
router.register(r"instance_status", instance_status.InstanceStatusViewSet, "instance_status")

if is_clickhouse_enabled():
    from ee.clickhouse.views.actions import ClickhouseActionsViewSet, LegacyClickhouseActionsViewSet
    from ee.clickhouse.views.cohort import ClickhouseCohortViewSet, LegacyClickhouseCohortViewSet
    from ee.clickhouse.views.element import ClickhouseElementViewSet, LegacyClickhouseElementViewSet
    from ee.clickhouse.views.events import ClickhouseEventsViewSet, LegacyClickhouseEventsViewSet
    from ee.clickhouse.views.insights import ClickhouseInsightsViewSet, LegacyClickhouseInsightsViewSet
    from ee.clickhouse.views.paths import ClickhousePathsViewSet, LegacyClickhousePathsViewSet
    from ee.clickhouse.views.person import ClickhousePersonViewSet, LegacyClickhousePersonViewSet
    from ee.clickhouse.views.session_recordings import ClickhouseSessionRecordingViewSet

    # Legacy endpoints CH (to be removed eventually)
    router.register(r"action", LegacyClickhouseActionsViewSet, basename="action")
    router.register(r"event", LegacyClickhouseEventsViewSet, basename="event")
    router.register(r"insight", LegacyClickhouseInsightsViewSet, basename="insight")
    router.register(r"person", LegacyClickhousePersonViewSet, basename="person")
    router.register(r"paths", LegacyClickhousePathsViewSet, basename="paths")
    router.register(r"element", LegacyClickhouseElementViewSet, basename="element")
    router.register(r"cohort", LegacyClickhouseCohortViewSet, basename="cohort")
    # Nested endpoints CH
    projects_router.register(r"actions", ClickhouseActionsViewSet, "project_actions", ["team_id"])
    projects_router.register(r"events", ClickhouseEventsViewSet, "project_events", ["team_id"])
    projects_router.register(r"insights", ClickhouseInsightsViewSet, "project_insights", ["team_id"])
    projects_router.register(r"persons", ClickhousePersonViewSet, "project_persons", ["team_id"])
    projects_router.register(r"paths", ClickhousePathsViewSet, "project_paths", ["team_id"])
    projects_router.register(r"elements", ClickhouseElementViewSet, "project_elements", ["team_id"])
    projects_router.register(r"cohorts", ClickhouseCohortViewSet, "project_cohorts", ["team_id"])
    projects_router.register(
        r"session_recordings", ClickhouseSessionRecordingViewSet, "project_session_recordings", ["team_id"],
    )
else:
    # Legacy endpoints PG (to be removed eventually)
    router.register(r"insight", insight.LegacyInsightViewSet)
    router.register(r"action", action.LegacyActionViewSet)
    router.register(r"person", person.LegacyPersonViewSet)
    router.register(r"event", event.LegacyEventViewSet)
    router.register(r"paths", paths.LegacyPathsViewSet, basename="paths")
    router.register(r"element", element.LegacyElementViewSet)
    router.register(r"cohort", cohort.LegacyCohortViewSet)
    # Nested endpoints PG
    projects_router.register(r"insights", insight.LegacyInsightViewSet, "project_insights", ["team_id"])
    projects_router.register(r"actions", action.ActionViewSet, "project_actions", ["team_id"])
    projects_router.register(r"persons", person.LegacyPersonViewSet, "project_persons", ["team_id"])
    projects_router.register(r"events", event.LegacyEventViewSet, "project_events", ["team_id"])
    projects_router.register(r"paths", paths.LegacyPathsViewSet, "project_paths", ["team_id"])
    projects_router.register(r"elements", element.LegacyElementViewSet, "project_elements", ["team_id"])
    projects_router.register(r"cohorts", cohort.LegacyCohortViewSet, "project_cohorts", ["team_id"])
    projects_router.register(
        r"session_recordings", session_recording.SessionRecordingViewSet, "project_session_recordings", ["team_id"],
    )
