from rest_framework import decorators, exceptions

from posthog.api.routing import DefaultRouterPlusPlus

from . import (
    action,
    annotation,
    async_migration,
    authentication,
    cohort,
    dashboard,
    element,
    event,
    event_definition,
    feature_flag,
    insight,
    instance_settings,
    instance_status,
    organization,
    organization_invite,
    organization_member,
    person,
    personal_api_key,
    plugin,
    plugin_log_entry,
    property_definition,
    session_recording,
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
router.register(r"annotation", annotation.LegacyAnnotationsViewSet)  # Should be completely unused now
router.register(r"feature_flag", feature_flag.LegacyFeatureFlagViewSet)  # Should be completely unused now
router.register(r"dashboard", dashboard.LegacyDashboardsViewSet)  # Should be completely unused now
router.register(r"dashboard_item", dashboard.LegacyInsightViewSet)  # To be deleted - unified into insight viewset
router.register(r"plugin_config", plugin.LegacyPluginConfigViewSet)

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
router.register(r"reset", authentication.PasswordResetViewSet, "password_reset")
router.register(r"users", user.UserViewSet)
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
router.register(r"instance_status", instance_status.InstanceStatusViewSet, "instance_status")
router.register(r"shared_dashboards", dashboard.SharedDashboardsViewSet)
router.register(r"async_migrations", async_migration.AsyncMigrationsViewset, "async_migrations")
router.register(r"instance_settings", instance_settings.InstanceSettingsViewset, "instance_settings")


from ee.clickhouse.views.cohort import ClickhouseCohortViewSet, LegacyClickhouseCohortViewSet
from ee.clickhouse.views.element import ClickhouseElementViewSet, LegacyClickhouseElementViewSet
from ee.clickhouse.views.events import ClickhouseEventsViewSet, LegacyClickhouseEventsViewSet
from ee.clickhouse.views.experiments import ClickhouseExperimentsViewSet
from ee.clickhouse.views.groups import ClickhouseGroupsTypesView, ClickhouseGroupsView
from ee.clickhouse.views.insights import ClickhouseInsightsViewSet, LegacyClickhouseInsightsViewSet
from ee.clickhouse.views.person import ClickhousePersonViewSet, LegacyClickhousePersonViewSet
from ee.clickhouse.views.session_recordings import ClickhouseSessionRecordingViewSet
from posthog.api.action import ActionViewSet

# Legacy endpoints CH (to be removed eventually)
router.register(r"event", LegacyClickhouseEventsViewSet, basename="event")  # Should be completely unused now
router.register(r"insight", LegacyClickhouseInsightsViewSet, basename="insight")  # Should be completely unused now
router.register(r"person", LegacyClickhousePersonViewSet, basename="person")
router.register(r"element", LegacyClickhouseElementViewSet, basename="element")
router.register(r"cohort", LegacyClickhouseCohortViewSet, basename="cohort")
# Nested endpoints CH
projects_router.register(r"actions", ActionViewSet, "project_actions", ["team_id"])
projects_router.register(r"events", ClickhouseEventsViewSet, "project_events", ["team_id"])
projects_router.register(r"groups", ClickhouseGroupsView, "project_groups", ["team_id"])
projects_router.register(r"groups_types", ClickhouseGroupsTypesView, "project_groups_types", ["team_id"])
projects_router.register(r"insights", ClickhouseInsightsViewSet, "project_insights", ["team_id"])
projects_router.register(r"persons", ClickhousePersonViewSet, "project_persons", ["team_id"])
projects_router.register(r"elements", ClickhouseElementViewSet, "project_elements", ["team_id"])
projects_router.register(r"cohorts", ClickhouseCohortViewSet, "project_cohorts", ["team_id"])
projects_router.register(r"experiments", ClickhouseExperimentsViewSet, "project_experiments", ["team_id"])
projects_router.register(
    r"session_recordings", ClickhouseSessionRecordingViewSet, "project_session_recordings", ["team_id"],
)
