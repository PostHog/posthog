from rest_framework import decorators, exceptions

from posthog.api.routing import DefaultRouterPlusPlus
from posthog.settings import EE_AVAILABLE

from . import (
    annotation,
    async_migration,
    authentication,
    dashboard,
    dead_letter_queue,
    event_definition,
    exports,
    feature_flag,
    instance_settings,
    instance_status,
    integration,
    kafka_inspector,
    organization,
    organization_domain,
    organization_invite,
    organization_member,
    personal_api_key,
    plugin,
    plugin_log_entry,
    property_definition,
    sharing,
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
project_dashboards_router = projects_router.register(
    r"dashboards", dashboard.DashboardsViewSet, "project_dashboards", ["team_id"]
)

projects_router.register(r"exports", exports.ExportedAssetViewSet, "exports", ["team_id"])
projects_router.register(r"integrations", integration.IntegrationViewSet, "integrations", ["team_id"])

# Organizations nested endpoints
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
    r"domains", organization_domain.OrganizationDomainViewset, "organization_domains", ["organization_id"],
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
router.register(r"login/precheck", authentication.LoginPrecheckViewSet)
router.register(r"reset", authentication.PasswordResetViewSet, "password_reset")
router.register(r"users", user.UserViewSet)
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
router.register(r"instance_status", instance_status.InstanceStatusViewSet, "instance_status")
router.register(r"dead_letter_queue", dead_letter_queue.DeadLetterQueueViewSet, "dead_letter_queue")
router.register(r"shared_dashboards", dashboard.SharedDashboardsViewSet)
router.register(r"async_migrations", async_migration.AsyncMigrationsViewset, "async_migrations")
router.register(r"instance_settings", instance_settings.InstanceSettingsViewset, "instance_settings")
router.register(r"kafka_inspector", kafka_inspector.KafkaInspectorViewSet, "kafka_inspector")


from posthog.api.action import ActionViewSet
from posthog.api.cohort import CohortViewSet, LegacyCohortViewSet
from posthog.api.element import ElementViewSet, LegacyElementViewSet
from posthog.api.event import EventViewSet, LegacyEventViewSet
from posthog.api.insight import InsightViewSet
from posthog.api.person import LegacyPersonViewSet, PersonViewSet
from posthog.api.session_recording import SessionRecordingViewSet

# Legacy endpoints CH (to be removed eventually)
router.register(r"cohort", LegacyCohortViewSet, basename="cohort")
router.register(r"element", LegacyElementViewSet, basename="element")
router.register(r"element", LegacyElementViewSet, basename="element")
router.register(r"event", LegacyEventViewSet, basename="event")

# Nested endpoints CH
projects_router.register(r"events", EventViewSet, "project_events", ["team_id"])
projects_router.register(r"actions", ActionViewSet, "project_actions", ["team_id"])
projects_router.register(r"cohorts", CohortViewSet, "project_cohorts", ["team_id"])
projects_router.register(r"persons", PersonViewSet, "project_persons", ["team_id"])
projects_router.register(r"elements", ElementViewSet, "project_elements", ["team_id"])
projects_router.register(
    r"session_recordings", SessionRecordingViewSet, "project_session_recordings", ["team_id"],
)

if EE_AVAILABLE:
    from ee.clickhouse.views.experiments import ClickhouseExperimentsViewSet
    from ee.clickhouse.views.groups import ClickhouseGroupsTypesView, ClickhouseGroupsView
    from ee.clickhouse.views.insights import ClickhouseInsightsViewSet
    from ee.clickhouse.views.person import EnterprisePersonViewSet, LegacyEnterprisePersonViewSet

    projects_router.register(r"experiments", ClickhouseExperimentsViewSet, "project_experiments", ["team_id"])
    projects_router.register(r"groups", ClickhouseGroupsView, "project_groups", ["team_id"])
    projects_router.register(r"groups_types", ClickhouseGroupsTypesView, "project_groups_types", ["team_id"])
    project_insights_router = projects_router.register(
        r"insights", ClickhouseInsightsViewSet, "project_insights", ["team_id"]
    )
    projects_router.register(r"persons", EnterprisePersonViewSet, "project_persons", ["team_id"])
    router.register(r"person", LegacyEnterprisePersonViewSet, basename="person")
else:
    project_insights_router = projects_router.register(r"insights", InsightViewSet, "project_insights", ["team_id"])
    projects_router.register(r"persons", PersonViewSet, "project_persons", ["team_id"])
    router.register(r"person", LegacyPersonViewSet, basename="person")


project_dashboards_router.register(
    r"sharing", sharing.SharingConfigurationViewSet, "project_dashboard_sharing", ["team_id", "dashboard_id"],
)

project_insights_router.register(
    r"sharing", sharing.SharingConfigurationViewSet, "project_insight_sharing", ["team_id", "insight_id"],
)
