from rest_framework import decorators, exceptions, viewsets
from rest_framework_extensions.routers import NestedRegistryItem

from posthog.api import data_color_theme, hog_flow, llm_gateway, metalytics, my_notifications, project
from posthog.api.batch_imports import BatchImportViewSet
from posthog.api.csp_reporting import CSPReportingViewSet
from posthog.api.routing import DefaultRouterPlusPlus
from posthog.api.wizard import http as wizard
from posthog.batch_exports import http as batch_exports
from posthog.settings import EE_AVAILABLE
from posthog.warehouse.api import (
    data_modeling_job,
    data_warehouse,
    external_data_schema,
    external_data_source,
    managed_viewset,
    modeling,
    query_tab_state,
    saved_query,
    saved_query_draft,
    table,
    view_link,
)
from posthog.warehouse.api.lineage import LineageViewSet

import products.logs.backend.api as logs
import products.links.backend.api as link
import products.tasks.backend.api as tasks
import products.endpoints.backend.api as endpoints
import products.live_debugger.backend.api as live_debugger
import products.revenue_analytics.backend.api as revenue_analytics
import products.early_access_features.backend.api as early_access_feature
import products.data_warehouse.backend.api.fix_hogql as fix_hogql
from products.desktop_recordings.backend.api import DesktopRecordingViewSet
from products.error_tracking.backend.api import (
    ErrorTrackingAssignmentRuleViewSet,
    ErrorTrackingExternalReferenceViewSet,
    ErrorTrackingFingerprintViewSet,
    ErrorTrackingGroupingRuleViewSet,
    ErrorTrackingIssueViewSet,
    ErrorTrackingReleaseViewSet,
    ErrorTrackingStackFrameViewSet,
    ErrorTrackingSuppressionRuleViewSet,
    ErrorTrackingSymbolSetViewSet,
    GitProviderFileLinksViewSet,
)
from products.llm_analytics.backend.api import (
    DatasetItemViewSet,
    DatasetViewSet,
    EvaluationRunViewSet,
    EvaluationViewSet,
    LLMProxyViewSet,
)
from products.notebooks.backend.api.notebook import NotebookViewSet
from products.user_interviews.backend.api import UserInterviewViewSet
from products.workflows.backend.api import MessageCategoryViewSet, MessagePreferencesViewSet, MessageTemplatesViewSet

from ee.api.vercel import vercel_installation, vercel_product, vercel_resource

from ..heatmaps.heatmaps_api import HeatmapScreenshotViewSet, HeatmapViewSet, LegacyHeatmapViewSet, SavedHeatmapViewSet
from ..session_recordings.session_recording_api import SessionRecordingViewSet
from ..session_recordings.session_recording_playlist_api import SessionRecordingPlaylistViewSet
from ..taxonomy import property_definition_api
from . import (
    advanced_activity_logs,
    alert,
    annotation,
    app_metrics,
    async_migration,
    authentication,
    cli_auth,
    comments,
    dead_letter_queue,
    debug_ch_queries,
    event_definition,
    event_schema,
    exports,
    feature_flag,
    flag_value,
    hog,
    hog_function,
    hog_function_template,
    ingestion_warnings,
    insight_variable,
    instance_settings,
    instance_status,
    integration,
    organization,
    organization_domain,
    organization_feature_flag,
    organization_invite,
    organization_member,
    personal_api_key,
    plugin,
    plugin_log_entry,
    proxy_record,
    query,
    scheduled_change,
    schema_property_group,
    search,
    sharing,
    survey,
    tagged_item,
    team,
    uploaded_media,
    user,
    web_vitals,
)
from .dashboards import dashboard, dashboard_templates
from .data_management import DataManagementViewSet
from .external_web_analytics import http as external_web_analytics
from .file_system import file_system, file_system_shortcut, persisted_folder
from .oauth_application import OAuthApplicationPublicMetadataViewSet
from .session import SessionViewSet


@decorators.api_view(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@decorators.authentication_classes([])
@decorators.permission_classes([])
def api_not_found(request):
    raise exceptions.NotFound(detail="Endpoint not found.")


router = DefaultRouterPlusPlus()

# Legacy endpoints shared (to be removed eventually)
router.register(r"dashboard", dashboard.LegacyDashboardsViewSet, "legacy_dashboards")  # Should be completely unused now
router.register(
    r"dashboard_item", dashboard.LegacyInsightViewSet, "legacy_insights"
)  # To be deleted - unified into insight viewset
router.register(r"plugin_config", plugin.LegacyPluginConfigViewSet, "legacy_plugin_configs")

router.register(r"feature_flag", feature_flag.LegacyFeatureFlagViewSet)  # Used for library side feature flag evaluation
router.register(r"llm_proxy", LLMProxyViewSet, "llm_proxy")
router.register(r"oauth_application/metadata", OAuthApplicationPublicMetadataViewSet, "oauth_application_metadata")
# Nested endpoints shared
projects_router = router.register(r"projects", project.RootProjectViewSet, "projects")
projects_router.register(r"environments", team.TeamViewSet, "project_environments", ["project_id"])
environments_router = router.register(r"environments", team.RootTeamViewSet, "environments")


def register_grandfathered_environment_nested_viewset(
    prefix: str, viewset: type[viewsets.GenericViewSet], basename: str, parents_query_lookups: list[str]
) -> tuple[NestedRegistryItem, NestedRegistryItem]:
    """
    Register the environment-specific viewset under both /environments/:team_id/ (correct endpoint)
    and /projects/:team_id/ (legacy, but supported for backward compatibility endpoint).
    DO NOT USE ON ANY NEW ENDPOINT YOU'RE ADDING!
    """
    if parents_query_lookups[0] != "team_id":
        raise ValueError("Only endpoints with team_id as the first parent query lookup can be environment-nested")
    if not basename.startswith("environment_"):
        raise ValueError("Only endpoints with a basename starting with `environment_` can be environment-nested")
    environment_nested = environments_router.register(prefix, viewset, basename, parents_query_lookups)
    legacy_project_nested = projects_router.register(
        prefix, viewset, basename.replace("environment_", "project_"), parents_query_lookups
    )
    return environment_nested, legacy_project_nested


environment_plugins_configs_router, legacy_project_plugins_configs_router = (
    register_grandfathered_environment_nested_viewset(
        r"plugin_configs", plugin.PluginConfigViewSet, "environment_plugin_configs", ["team_id"]
    )
)
environment_plugins_configs_router.register(
    r"logs",
    plugin_log_entry.PluginLogEntryViewSet,
    "environment_plugin_config_logs",
    ["team_id", "plugin_config_id"],
)
legacy_project_plugins_configs_router.register(
    r"logs",
    plugin_log_entry.PluginLogEntryViewSet,
    "project_plugin_config_logs",
    ["team_id", "plugin_config_id"],
)
register_grandfathered_environment_nested_viewset(
    r"pipeline_transformation_configs",
    plugin.PipelineTransformationsConfigsViewSet,
    "environment_pipeline_transformation_configs",
    ["team_id"],
)
register_grandfathered_environment_nested_viewset(
    r"pipeline_destination_configs",
    plugin.PipelineDestinationsConfigsViewSet,
    "environment_pipeline_destination_configs",
    ["team_id"],
)
register_grandfathered_environment_nested_viewset(
    r"pipeline_frontend_apps_configs",
    plugin.PipelineFrontendAppsConfigsViewSet,
    "environment_pipeline_frontend_apps_configs",
    ["team_id"],
)
register_grandfathered_environment_nested_viewset(
    r"pipeline_import_apps_configs",
    plugin.PipelineImportAppsConfigsViewSet,
    "environment_pipeline_import_apps_configs",
    ["team_id"],
)

projects_router.register(r"annotations", annotation.AnnotationsViewSet, "project_annotations", ["project_id"])
projects_router.register(
    r"activity_log",
    advanced_activity_logs.ActivityLogViewSet,
    "project_activity_log",
    ["project_id"],
)
projects_router.register(
    r"advanced_activity_logs",
    advanced_activity_logs.AdvancedActivityLogsViewSet,
    "project_advanced_activity_logs",
    ["project_id"],
)
projects_router.register(
    r"my_notifications",
    my_notifications.MyNotificationsViewSet,
    "project_notifications",
    ["project_id"],
)
project_feature_flags_router = projects_router.register(
    r"feature_flags",
    feature_flag.FeatureFlagViewSet,
    "project_feature_flags",
    ["project_id"],
)
project_features_router = projects_router.register(
    r"early_access_feature",
    early_access_feature.EarlyAccessFeatureViewSet,
    "project_early_access_feature",
    ["project_id"],
)

# Tasks endpoints
project_tasks_router = projects_router.register(r"tasks", tasks.TaskViewSet, "project_tasks", ["team_id"])
project_tasks_router.register(r"runs", tasks.TaskRunViewSet, "project_task_runs", ["team_id", "task_id"])

# Agents endpoints
projects_router.register(r"agents", tasks.AgentDefinitionViewSet, "project_agents", ["team_id"])

# Workflows endpoints
projects_router.register(r"llm_gateway", llm_gateway.http.LLMGatewayViewSet, "project_llm_gateway", ["team_id"])

projects_router.register(r"surveys", survey.SurveyViewSet, "project_surveys", ["project_id"])
projects_router.register(
    r"dashboard_templates",
    dashboard_templates.DashboardTemplateViewSet,
    "project_dashboard_templates",
    ["project_id"],
)
environment_dashboards_router, legacy_project_dashboards_router = register_grandfathered_environment_nested_viewset(
    r"dashboards", dashboard.DashboardsViewSet, "environment_dashboards", ["team_id"]
)

register_grandfathered_environment_nested_viewset(
    r"exports", exports.ExportedAssetViewSet, "environment_exports", ["team_id"]
)
register_grandfathered_environment_nested_viewset(
    r"integrations", integration.IntegrationViewSet, "environment_integrations", ["team_id"]
)
register_grandfathered_environment_nested_viewset(
    r"ingestion_warnings",
    ingestion_warnings.IngestionWarningsViewSet,
    "environment_ingestion_warnings",
    ["team_id"],
)

projects_router.register(
    r"data_management",
    DataManagementViewSet,
    "project_data_management",
    ["project_id"],
)

projects_router.register(
    r"scheduled_changes",
    scheduled_change.ScheduledChangeViewSet,
    "project_scheduled_changes",
    ["project_id"],
)

register_grandfathered_environment_nested_viewset(
    r"file_system", file_system.FileSystemViewSet, "environment_file_system", ["team_id"]
)

register_grandfathered_environment_nested_viewset(
    r"file_system_shortcut",
    file_system_shortcut.FileSystemShortcutViewSet,
    "environment_file_system_shortcut",
    ["team_id"],
)

register_grandfathered_environment_nested_viewset(
    r"persisted_folder",
    persisted_folder.PersistedFolderViewSet,
    "environment_persisted_folder",
    ["team_id"],
)

environment_app_metrics_router, legacy_project_app_metrics_router = register_grandfathered_environment_nested_viewset(
    r"app_metrics", app_metrics.AppMetricsViewSet, "environment_app_metrics", ["team_id"]
)
environment_app_metrics_router.register(
    r"historical_exports",
    app_metrics.HistoricalExportsAppMetricsViewSet,
    "environment_app_metrics_historical_exports",
    ["team_id", "plugin_config_id"],
)
legacy_project_app_metrics_router.register(
    r"historical_exports",
    app_metrics.HistoricalExportsAppMetricsViewSet,
    "project_app_metrics_historical_exports",
    ["team_id", "plugin_config_id"],
)

environment_batch_exports_router, legacy_project_batch_exports_router = (
    register_grandfathered_environment_nested_viewset(
        r"batch_exports", batch_exports.BatchExportViewSet, "environment_batch_exports", ["team_id"]
    )
)
environment_batch_exports_router.register(
    r"runs", batch_exports.BatchExportRunViewSet, "environment_batch_export_runs", ["team_id", "batch_export_id"]
)
legacy_project_batch_exports_router.register(
    r"runs", batch_exports.BatchExportRunViewSet, "project_batch_export_runs", ["team_id", "batch_export_id"]
)
environment_batch_exports_router.register(
    r"backfills",
    batch_exports.BatchExportBackfillViewSet,
    "environment_batch_export_backfills",
    ["team_id", "batch_export_id"],
)
legacy_project_batch_exports_router.register(
    r"backfills",
    batch_exports.BatchExportBackfillViewSet,
    "project_batch_export_backfills",
    ["team_id", "batch_export_id"],
)

register_grandfathered_environment_nested_viewset(
    r"warehouse_tables", table.TableViewSet, "environment_warehouse_tables", ["team_id"]
)
register_grandfathered_environment_nested_viewset(
    r"warehouse_saved_queries",
    saved_query.DataWarehouseSavedQueryViewSet,
    "environment_warehouse_saved_queries",
    ["team_id"],
)
register_grandfathered_environment_nested_viewset(
    r"warehouse_view_links",
    view_link.ViewLinkViewSet,
    "environment_warehouse_view_links",
    ["team_id"],
)
register_grandfathered_environment_nested_viewset(
    r"warehouse_view_link", view_link.ViewLinkViewSet, "environment_warehouse_view_link", ["team_id"]
)

projects_router.register(
    r"event_definitions",
    event_definition.EventDefinitionViewSet,
    "project_event_definitions",
    ["project_id"],
)
projects_router.register(
    r"property_definitions",
    property_definition_api.PropertyDefinitionViewSet,
    "project_property_definitions",
    ["project_id"],
)
projects_router.register(
    r"schema_property_groups",
    schema_property_group.SchemaPropertyGroupViewSet,
    "project_schema_property_groups",
    ["project_id"],
)
projects_router.register(
    r"event_schemas",
    event_schema.EventSchemaViewSet,
    "project_event_schemas",
    ["project_id"],
)

projects_router.register(r"uploaded_media", uploaded_media.MediaViewSet, "project_media", ["project_id"])

projects_router.register(r"tags", tagged_item.TaggedItemViewSet, "project_tags", ["project_id"])
projects_router.register(
    r"web_analytics",
    external_web_analytics.ExternalWebAnalyticsViewSet,
    "project_external_web_analytics",
    ["project_id"],
)
register_grandfathered_environment_nested_viewset(r"query", query.QueryViewSet, "environment_query", ["team_id"])

# External data resources
register_grandfathered_environment_nested_viewset(
    r"external_data_sources",
    external_data_source.ExternalDataSourceViewSet,
    "environment_external_data_sources",
    ["team_id"],
)
register_grandfathered_environment_nested_viewset(
    r"data_warehouse",
    data_warehouse.DataWarehouseViewSet,
    "environment_data_warehouse",
    ["team_id"],
)
projects_router.register(
    r"warehouse_dag",
    modeling.DataWarehouseModelDagViewSet,
    "project_warehouse_dag",
    ["team_id"],
)
projects_router.register(
    r"warehouse_model_paths",
    modeling.DataWarehouseModelPathViewSet,
    "project_warehouse_model_paths",
    ["team_id"],
)
projects_router.register(
    r"query_tab_state",
    query_tab_state.QueryTabStateViewSet,
    "project_query_tab_state",
    ["project_id"],
)

register_grandfathered_environment_nested_viewset(
    r"external_data_schemas",
    external_data_schema.ExternalDataSchemaViewset,
    "environment_external_data_schemas",
    ["team_id"],
)
environments_router.register(
    r"fix_hogql",
    fix_hogql.FixHogQLViewSet,
    "project_fix_hogql",
    ["team_id"],
)
environments_router.register(
    r"warehouse_saved_query_drafts",
    saved_query_draft.DataWarehouseSavedQueryDraftViewSet,
    "environment_warehouse_saved_query_drafts",
    ["team_id"],
)
environments_router.register(
    r"managed_viewsets",
    managed_viewset.DataWarehouseManagedViewSetViewSet,
    "environment_managed_viewsets",
    ["team_id"],
)

# Organizations nested endpoints
organizations_router = router.register(r"organizations", organization.OrganizationViewSet, "organizations")
organizations_router.register(r"projects", project.ProjectViewSet, "organization_projects", ["organization_id"])
organizations_router.register(
    r"batch_exports", batch_exports.BatchExportOrganizationViewSet, "batch_exports", ["organization_id"]
)
organization_plugins_router = organizations_router.register(
    r"plugins", plugin.PluginViewSet, "organization_plugins", ["organization_id"]
)
organizations_router.register(
    r"pipeline_transformations",
    plugin.PipelineTransformationsViewSet,
    "organization_pipeline_transformations",
    ["organization_id"],
)
organizations_router.register(
    r"pipeline_destinations",
    plugin.PipelineDestinationsViewSet,
    "organization_pipeline_destinations",
    ["organization_id"],
)
organizations_router.register(
    r"pipeline_frontend_apps",
    plugin.PipelineFrontendAppsViewSet,
    "organization_pipeline_frontend_apps",
    ["organization_id"],
)
organizations_router.register(
    r"pipeline_import_apps",
    plugin.PipelineImportAppsViewSet,
    "organization_pipeline_import_apps",
    ["organization_id"],
)
organizations_router.register(
    r"members",
    organization_member.OrganizationMemberViewSet,
    "organization_members",
    ["organization_id"],
)
organizations_router.register(
    r"invites",
    organization_invite.OrganizationInviteViewSet,
    "organization_invites",
    ["organization_id"],
)
organizations_router.register(
    r"domains",
    organization_domain.OrganizationDomainViewset,
    "organization_domains",
    ["organization_id"],
)
organizations_router.register(
    r"proxy_records",
    proxy_record.ProxyRecordViewset,
    "proxy_records",
    ["organization_id"],
)
organizations_router.register(
    r"feature_flags",
    organization_feature_flag.OrganizationFeatureFlagView,
    "organization_feature_flags",
    ["organization_id"],
)

# General endpoints (shared across CH & PG)
router.register(r"login", authentication.LoginViewSet, "login")
router.register(r"login/token", authentication.TwoFactorViewSet, "login_token")
router.register(r"login/precheck", authentication.LoginPrecheckViewSet, "login_precheck")
router.register(r"login/email-mfa", authentication.EmailMFAViewSet, "login_email_mfa")
router.register(r"reset", authentication.PasswordResetViewSet, "password_reset")
router.register(r"users", user.UserViewSet, "users")
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
router.register(r"cli-auth", cli_auth.CLIAuthViewSet, "cli_auth")
router.register(r"instance_status", instance_status.InstanceStatusViewSet, "instance_status")
router.register(r"dead_letter_queue", dead_letter_queue.DeadLetterQueueViewSet, "dead_letter_queue")
router.register(r"async_migrations", async_migration.AsyncMigrationsViewset, "async_migrations")
router.register(r"instance_settings", instance_settings.InstanceSettingsViewset, "instance_settings")
router.register("debug_ch_queries/", debug_ch_queries.DebugCHQueries, "debug_ch_queries")

from posthog.api.action import ActionViewSet  # noqa: E402
from posthog.api.cohort import CohortViewSet, LegacyCohortViewSet  # noqa: E402
from posthog.api.element import ElementViewSet, LegacyElementViewSet  # noqa: E402
from posthog.api.event import EventViewSet, LegacyEventViewSet  # noqa: E402
from posthog.api.insight import InsightViewSet  # noqa: E402
from posthog.api.person import LegacyPersonViewSet, PersonViewSet  # noqa: E402
from posthog.api.web_experiment import WebExperimentViewSet  # noqa: E402

# Legacy endpoints CH (to be removed eventually)
router.register(r"cohort", LegacyCohortViewSet, basename="cohort")
router.register(r"element", LegacyElementViewSet, basename="element")
router.register(r"heatmap", LegacyHeatmapViewSet, basename="heatmap")
router.register(r"event", LegacyEventViewSet, basename="event")

# Nested endpoints CH
register_grandfathered_environment_nested_viewset(r"events", EventViewSet, "environment_events", ["team_id"])
projects_router.register(r"actions", ActionViewSet, "project_actions", ["project_id"])
projects_router.register(r"web_experiments", WebExperimentViewSet, "web_experiments", ["project_id"])
projects_router.register(r"cohorts", CohortViewSet, "project_cohorts", ["project_id"])

register_grandfathered_environment_nested_viewset(
    r"elements",
    ElementViewSet,
    "environment_elements",
    ["team_id"],  # TODO: Can be removed?
)

environment_sessions_recordings_router, legacy_project_session_recordings_router = (
    register_grandfathered_environment_nested_viewset(
        r"session_recordings",
        SessionRecordingViewSet,
        "environment_session_recordings",
        ["team_id"],
    )
)

register_grandfathered_environment_nested_viewset(
    r"session_recording_playlists",
    SessionRecordingPlaylistViewSet,
    "environment_session_recording_playlist",
    ["team_id"],
)

register_grandfathered_environment_nested_viewset(r"heatmaps", HeatmapViewSet, "environment_heatmaps", ["team_id"])
register_grandfathered_environment_nested_viewset(
    r"heatmap_screenshots", HeatmapScreenshotViewSet, "environment_heatmap_screenshots", ["team_id"]
)
register_grandfathered_environment_nested_viewset(r"saved", SavedHeatmapViewSet, "environment_saved", ["team_id"])
register_grandfathered_environment_nested_viewset(r"sessions", SessionViewSet, "environment_sessions", ["team_id"])

if EE_AVAILABLE:
    from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutViewSet
    from ee.clickhouse.views.experiment_saved_metrics import ExperimentSavedMetricViewSet
    from ee.clickhouse.views.experiments import EnterpriseExperimentsViewSet
    from ee.clickhouse.views.groups import GroupsTypesViewSet, GroupsViewSet, GroupUsageMetricViewSet
    from ee.clickhouse.views.insights import EnterpriseInsightsViewSet
    from ee.clickhouse.views.person import EnterprisePersonViewSet, LegacyEnterprisePersonViewSet

    projects_router.register(r"experiments", EnterpriseExperimentsViewSet, "project_experiments", ["project_id"])
    projects_router.register(
        r"experiment_holdouts", ExperimentHoldoutViewSet, "project_experiment_holdouts", ["project_id"]
    )
    projects_router.register(
        r"experiment_saved_metrics", ExperimentSavedMetricViewSet, "project_experiment_saved_metrics", ["project_id"]
    )
    register_grandfathered_environment_nested_viewset(r"groups", GroupsViewSet, "environment_groups", ["team_id"])
    group_types_router = projects_router.register(
        r"groups_types", GroupsTypesViewSet, "project_groups_types", ["project_id"]
    )
    group_types_router.register(
        r"metrics", GroupUsageMetricViewSet, "project_groups_metrics", ["project_id", "group_type_index"]
    )
    environment_insights_router, legacy_project_insights_router = register_grandfathered_environment_nested_viewset(
        r"insights", EnterpriseInsightsViewSet, "environment_insights", ["team_id"]
    )
    register_grandfathered_environment_nested_viewset(
        r"persons", EnterprisePersonViewSet, "environment_persons", ["team_id"]
    )
    router.register(r"person", LegacyEnterprisePersonViewSet, "persons")
    vercel_installations_router = router.register(
        r"vercel/v1/installations",
        vercel_installation.VercelInstallationViewSet,
        "vercel_installations",
    )
    vercel_installations_router.register(
        r"resources",
        vercel_resource.VercelResourceViewSet,
        "vercel_installation_resources",
        ["installation_id"],
    )
    router.register(
        r"vercel/v1/products",
        vercel_product.VercelProductViewSet,
        "vercel_products",
    )

else:
    environment_insights_router, legacy_project_insights_router = register_grandfathered_environment_nested_viewset(
        r"insights", InsightViewSet, "environment_insights", ["team_id"]
    )
    register_grandfathered_environment_nested_viewset(r"persons", PersonViewSet, "environment_persons", ["team_id"])
    router.register(r"person", LegacyPersonViewSet, "persons")

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

environment_insights_router.register(
    r"sharing",
    sharing.SharingConfigurationViewSet,
    "environment_insight_sharing",
    ["team_id", "insight_id"],
)
legacy_project_insights_router.register(
    r"sharing",
    sharing.SharingConfigurationViewSet,
    "project_insight_sharing",
    ["team_id", "insight_id"],
)

environment_insights_router.register(
    "thresholds",
    alert.ThresholdViewSet,
    "environment_insight_thresholds",
    ["team_id", "insight_id"],
)
legacy_project_insights_router.register(
    "thresholds",
    alert.ThresholdViewSet,
    "project_insight_thresholds",
    ["team_id", "insight_id"],
)

environment_sessions_recordings_router.register(
    r"sharing",
    sharing.SharingConfigurationViewSet,
    "environment_recording_sharing",
    ["team_id", "recording_id"],
)
legacy_project_session_recordings_router.register(
    r"sharing",
    sharing.SharingConfigurationViewSet,
    "project_recording_sharing",
    ["team_id", "recording_id"],
)

projects_router.register(
    r"notebooks",
    NotebookViewSet,
    "project_notebooks",
    ["project_id"],
)

environments_router.register(
    r"error_tracking/releases",
    ErrorTrackingReleaseViewSet,
    "project_error_tracking_release",
    ["team_id"],
)

environments_router.register(
    r"error_tracking/symbol_sets",
    ErrorTrackingSymbolSetViewSet,
    "project_error_tracking_symbol_set",
    ["team_id"],
)

environments_router.register(
    r"error_tracking/assignment_rules",
    ErrorTrackingAssignmentRuleViewSet,
    "project_error_tracking_assignment_rule",
    ["team_id"],
)

environments_router.register(
    r"error_tracking/grouping_rules",
    ErrorTrackingGroupingRuleViewSet,
    "project_error_tracking_grouping_rule",
    ["team_id"],
)

environments_router.register(
    r"error_tracking/suppression_rules",
    ErrorTrackingSuppressionRuleViewSet,
    "project_error_tracking_suppression_rule",
    ["team_id"],
)

environments_router.register(
    r"error_tracking/fingerprints",
    ErrorTrackingFingerprintViewSet,
    "project_error_tracking_fingerprint",
    ["team_id"],
)

environments_router.register(
    r"error_tracking/issues",
    ErrorTrackingIssueViewSet,
    "project_error_tracking_issue",
    ["team_id"],
)

environments_router.register(
    r"error_tracking/external_references",
    ErrorTrackingExternalReferenceViewSet,
    "project_error_tracking_external_references",
    ["team_id"],
)

environments_router.register(
    r"error_tracking/stack_frames",
    ErrorTrackingStackFrameViewSet,
    "project_error_tracking_stack_frames",
    ["team_id"],
)

environments_router.register(
    r"error_tracking/git-provider-file-links",
    GitProviderFileLinksViewSet,
    "project_error_tracking_git_provider_file_links",
    ["team_id"],
)

projects_router.register(
    r"live_debugger_breakpoints",
    live_debugger.LiveDebuggerBreakpointViewSet,
    "project_live_debugger_breakpoints",
    ["project_id"],
)

projects_router.register(
    r"comments",
    comments.CommentViewSet,
    "project_comments",
    ["project_id"],
)

register_grandfathered_environment_nested_viewset(
    r"hog_functions",
    hog_function.HogFunctionViewSet,
    "environment_hog_functions",
    ["team_id"],
)

register_grandfathered_environment_nested_viewset(
    r"hog_flows",
    hog_flow.HogFlowViewSet,
    "environment_hog_flows",
    ["team_id"],
)

projects_router.register(r"links", link.LinkViewSet, "environment_links", ["team_id"])

projects_router.register(
    r"hog_function_templates",
    hog_function_template.PublicHogFunctionTemplateViewSet,
    "project_hog_function_templates",
    ["project_id"],
)

projects_router.register(
    r"managed_migrations",
    BatchImportViewSet,
    "project_managed_migrations",
    ["project_id"],
)

projects_router.register(
    r"hog",
    hog.HogViewSet,
    "hog",
    ["team_id"],
)

register_grandfathered_environment_nested_viewset(
    r"metalytics",
    metalytics.MetalyticsViewSet,
    "environment_metalytics",
    ["team_id"],
)

register_grandfathered_environment_nested_viewset(
    r"insight_variables",
    insight_variable.InsightVariableViewSet,
    "environment_insight_variables",
    ["team_id"],
)

register_grandfathered_environment_nested_viewset(
    r"alerts",
    alert.AlertViewSet,
    "environment_alerts",
    ["team_id"],
)

projects_router.register(r"search", search.SearchViewSet, "project_search", ["project_id"])

register_grandfathered_environment_nested_viewset(
    r"data_color_themes", data_color_theme.DataColorThemeViewSet, "environment_data_color_themes", ["team_id"]
)

environments_router.register(
    r"web_vitals",
    web_vitals.WebVitalsViewSet,
    "environment_web_vitals",
    ["team_id"],
)

router.register(r"wizard", wizard.SetupWizardViewSet, "wizard")

register_grandfathered_environment_nested_viewset(
    r"data_modeling_jobs",
    data_modeling_job.DataModelingJobViewSet,
    "environment_data_modeling_jobs",
    ["team_id"],
)

environments_router.register(r"lineage", LineageViewSet, "environment_lineage", ["team_id"])

environments_router.register(
    r"messaging_templates",
    MessageTemplatesViewSet,
    "environment_messaging_templates",
    ["team_id"],
)

environments_router.register(
    r"messaging_categories",
    MessageCategoryViewSet,
    "environment_messaging_categories",
    ["team_id"],
)

environments_router.register(
    r"messaging_preferences",
    MessagePreferencesViewSet,
    "environment_messaging_preferences",
    ["team_id"],
)

# Logs endpoints
register_grandfathered_environment_nested_viewset(r"logs", logs.LogsViewSet, "environment_logs", ["team_id"])

register_grandfathered_environment_nested_viewset(
    r"endpoints", endpoints.EndpointViewSet, "environment_endpoints", ["team_id"]
)

environments_router.register(
    r"user_interviews",
    UserInterviewViewSet,
    "environment_user_interviews",
    ["team_id"],
)

environments_router.register(
    r"desktop_recordings",
    DesktopRecordingViewSet,
    "environment_desktop_recordings",
    ["team_id"],
)

environments_router.register(
    r"csp-reporting",
    CSPReportingViewSet,
    "environment_csp_reporting",
    ["team_id"],
)

environments_router.register(
    r"revenue_analytics/taxonomy",
    revenue_analytics.RevenueAnalyticsTaxonomyViewSet,
    "environment_revenue_analytics_taxonomy",
    ["team_id"],
)

projects_router.register(
    r"flag_value",
    flag_value.FlagValueViewSet,
    "project_flag_value",
    ["project_id"],
)

register_grandfathered_environment_nested_viewset(
    r"datasets",
    DatasetViewSet,
    "environment_datasets",
    ["team_id"],
)

register_grandfathered_environment_nested_viewset(
    r"dataset_items",
    DatasetItemViewSet,
    "environment_dataset_items",
    ["team_id"],
)

environments_router.register(
    r"evaluations",
    EvaluationViewSet,
    "environment_evaluations",
    ["team_id"],
)

environments_router.register(
    r"evaluation_runs",
    EvaluationRunViewSet,
    "environment_evaluation_runs",
    ["team_id"],
)
