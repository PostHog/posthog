from rest_framework import decorators, exceptions
import products.early_access_features.backend.api as early_access_feature
import products.editor.backend.api as editorApi
from posthog.api import data_color_theme, metalytics, wizard
from posthog.api.routing import DefaultRouterPlusPlus
from posthog.batch_exports import http as batch_exports
from posthog.settings import EE_AVAILABLE
from posthog.warehouse.api import (
    external_data_schema,
    external_data_source,
    modeling,
    saved_query,
    table,
    view_link,
    query_tab_state,
    data_modeling_job,
)

from ..heatmaps.heatmaps_api import HeatmapViewSet, LegacyHeatmapViewSet
from ..session_recordings.session_recording_api import SessionRecordingViewSet
from ..session_recordings.session_recording_playlist_api import SessionRecordingPlaylistViewSet
from ..taxonomy import property_definition_api
from . import (
    activity_log,
    alert,
    annotation,
    app_metrics,
    async_migration,
    authentication,
    comments,
    dead_letter_queue,
    debug_ch_queries,
    error_tracking,
    event_definition,
    exports,
    feature_flag,
    file_system,
    hog,
    hog_function,
    hog_function_template,
    ingestion_warnings,
    insight_variable,
    instance_settings,
    instance_status,
    integration,
    notebook,
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
    search,
    sharing,
    survey,
    tagged_item,
    team,
    uploaded_media,
    user,
    user_group,
    web_vitals,
)
from .dashboards import dashboard, dashboard_templates
from .data_management import DataManagementViewSet
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
router.register(r"llm_proxy", editorApi.LLMProxyViewSet, "llm_proxy")

# Nested endpoints shared
projects_router = router.register(r"projects", team.RootTeamViewSet, "projects")


project_plugins_configs_router = projects_router.register(
    r"plugin_configs", plugin.PluginConfigViewSet, "project_plugin_configs", ["team_id"]
)
project_plugins_configs_router.register(
    r"logs",
    plugin_log_entry.PluginLogEntryViewSet,
    "project_plugin_config_logs",
    ["team_id", "plugin_config_id"],
)
projects_router.register(
    r"pipeline_transformation_configs",
    plugin.PipelineTransformationsConfigsViewSet,
    "project_pipeline_transformation_configs",
    ["team_id"],
)
projects_router.register(
    r"pipeline_destination_configs",
    plugin.PipelineDestinationsConfigsViewSet,
    "project_pipeline_destination_configs",
    ["team_id"],
)
projects_router.register(
    r"pipeline_frontend_apps_configs",
    plugin.PipelineFrontendAppsConfigsViewSet,
    "project_pipeline_frontend_apps_configs",
    ["team_id"],
)
projects_router.register(
    r"pipeline_import_apps_configs",
    plugin.PipelineImportAppsConfigsViewSet,
    "project_pipeline_import_apps_configs",
    ["team_id"],
)

projects_router.register(r"annotations", annotation.AnnotationsViewSet, "project_annotations", ["team_id"])
projects_router.register(
    r"activity_log",
    activity_log.ActivityLogViewSet,
    "project_activity_log",
    ["team_id"],
)
project_feature_flags_router = projects_router.register(
    r"feature_flags",
    feature_flag.FeatureFlagViewSet,
    "project_feature_flags",
    ["team_id"],
)
project_features_router = projects_router.register(
    r"early_access_feature",
    early_access_feature.EarlyAccessFeatureViewSet,
    "project_early_access_feature",
    ["team_id"],
)
projects_router.register(r"surveys", survey.SurveyViewSet, "project_surveys", ["team_id"])

projects_router.register(
    r"dashboard_templates",
    dashboard_templates.DashboardTemplateViewSet,
    "project_dashboard_templates",
    ["team_id"],
)
project_dashboards_router = projects_router.register(
    r"dashboards", dashboard.DashboardsViewSet, "project_dashboards", ["team_id"]
)

projects_router.register(r"exports", exports.ExportedAssetViewSet, "project_exports", ["team_id"])
projects_router.register(r"integrations", integration.IntegrationViewSet, "project_integrations", ["team_id"])
projects_router.register(
    r"ingestion_warnings",
    ingestion_warnings.IngestionWarningsViewSet,
    "project_ingestion_warnings",
    ["team_id"],
)

projects_router.register(
    r"data_management",
    DataManagementViewSet,
    "project_data_management",
    ["team_id"],
)

projects_router.register(
    r"scheduled_changes",
    scheduled_change.ScheduledChangeViewSet,
    "project_scheduled_changes",
    ["team_id"],
)

projects_router.register(r"file_system", file_system.FileSystemViewSet, "project_file_system", ["team_id"])

project_app_metrics_router = projects_router.register(
    r"app_metrics", app_metrics.AppMetricsViewSet, "project_app_metrics", ["team_id"]
)
project_app_metrics_router.register(
    r"historical_exports",
    app_metrics.HistoricalExportsAppMetricsViewSet,
    "project_app_metrics_historical_exports",
    ["team_id", "plugin_config_id"],
)

project_batch_exports_router = projects_router.register(
    r"batch_exports", batch_exports.BatchExportViewSet, "project_batch_exports", ["team_id"]
)
project_batch_exports_router.register(
    r"runs", batch_exports.BatchExportRunViewSet, "project_batch_export_runs", ["team_id", "batch_export_id"]
)
project_batch_exports_router.register(
    r"backfills",
    batch_exports.BatchExportBackfillViewSet,
    "project_batch_export_backfills",
    ["team_id", "batch_export_id"],
)

projects_router.register(r"warehouse_tables", table.TableViewSet, "project_warehouse_tables", ["team_id"])
projects_router.register(
    r"warehouse_saved_queries",
    saved_query.DataWarehouseSavedQueryViewSet,
    "project_warehouse_saved_queries",
    ["team_id"],
)
projects_router.register(
    r"warehouse_view_links",
    view_link.ViewLinkViewSet,
    "project_warehouse_view_links",
    ["team_id"],
)
projects_router.register(r"warehouse_view_link", view_link.ViewLinkViewSet, "project_warehouse_view_link", ["team_id"])

projects_router.register(
    r"event_definitions",
    event_definition.EventDefinitionViewSet,
    "project_event_definitions",
    ["team_id"],
)
projects_router.register(
    r"property_definitions",
    property_definition_api.PropertyDefinitionViewSet,
    "project_property_definitions",
    ["team_id"],
)

projects_router.register(r"uploaded_media", uploaded_media.MediaViewSet, "project_media", ["team_id"])

projects_router.register(r"tags", tagged_item.TaggedItemViewSet, "project_tags", ["team_id"])
projects_router.register(r"query", query.QueryViewSet, "project_query", ["team_id"])

# External data resources
projects_router.register(
    r"external_data_sources",
    external_data_source.ExternalDataSourceViewSet,
    "project_external_data_sources",
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
    ["team_id"],
)

projects_router.register(
    r"external_data_schemas",
    external_data_schema.ExternalDataSchemaViewset,
    "project_external_data_schemas",
    ["team_id"],
)

# Organizations nested endpoints
organizations_router = router.register(r"organizations", organization.OrganizationViewSet, "organizations")
organizations_router.register(r"projects", team.TeamViewSet, "organization_projects", ["organization_id"])
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
router.register(r"reset", authentication.PasswordResetViewSet, "password_reset")
router.register(r"users", user.UserViewSet, "users")
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
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
projects_router.register(r"events", EventViewSet, "project_events", ["team_id"])
projects_router.register(r"actions", ActionViewSet, "project_actions", ["team_id"])
projects_router.register(r"web_experiments", WebExperimentViewSet, "web_experiments", ["team_id"])
projects_router.register(r"cohorts", CohortViewSet, "project_cohorts", ["team_id"])
projects_router.register(
    r"elements",
    ElementViewSet,
    "project_elements",
    ["team_id"],  # TODO: Can be removed?
)
project_session_recordings_router = projects_router.register(
    r"session_recordings",
    SessionRecordingViewSet,
    "project_session_recordings",
    ["team_id"],
)

projects_router.register(
    r"session_recording_playlists",
    SessionRecordingPlaylistViewSet,
    "project_session_recording_playlist",
    ["team_id"],
)


projects_router.register(r"heatmaps", HeatmapViewSet, "project_heatmaps", ["team_id"])
projects_router.register(r"sessions", SessionViewSet, "project_sessions", ["team_id"])

if EE_AVAILABLE:
    from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutViewSet
    from ee.clickhouse.views.experiment_saved_metrics import (
        ExperimentSavedMetricViewSet,
    )
    from ee.clickhouse.views.experiments import EnterpriseExperimentsViewSet
    from ee.clickhouse.views.groups import GroupsTypesViewSet, GroupsViewSet
    from ee.clickhouse.views.insights import EnterpriseInsightsViewSet
    from ee.clickhouse.views.person import (
        EnterprisePersonViewSet,
        LegacyEnterprisePersonViewSet,
    )

    projects_router.register(r"experiments", EnterpriseExperimentsViewSet, "project_experiments", ["team_id"])
    projects_router.register(
        r"experiment_holdouts", ExperimentHoldoutViewSet, "project_experiment_holdouts", ["team_id"]
    )
    projects_router.register(
        r"experiment_saved_metrics", ExperimentSavedMetricViewSet, "project_experiment_saved_metrics", ["team_id"]
    )
    projects_router.register(r"groups", GroupsViewSet, "project_groups", ["team_id"])
    projects_router.register(r"groups_types", GroupsTypesViewSet, "project_groups_types", ["team_id"])
    project_insights_router = projects_router.register(
        r"insights", EnterpriseInsightsViewSet, "project_insights", ["team_id"]
    )
    projects_router.register(r"persons", EnterprisePersonViewSet, "project_persons", ["team_id"])
    router.register(r"person", LegacyEnterprisePersonViewSet, "persons")
else:
    project_insights_router = projects_router.register(r"insights", InsightViewSet, "project_insights", ["team_id"])
    projects_router.register(r"persons", PersonViewSet, "project_persons", ["team_id"])
    router.register(r"person", LegacyPersonViewSet, "persons")


project_dashboards_router.register(
    r"sharing",
    sharing.SharingConfigurationViewSet,
    "project_dashboard_sharing",
    ["team_id", "dashboard_id"],
)

project_insights_router.register(
    r"sharing",
    sharing.SharingConfigurationViewSet,
    "project_insight_sharing",
    ["team_id", "insight_id"],
)

project_insights_router.register(
    "thresholds",
    alert.ThresholdViewSet,
    "project_insight_thresholds",
    ["team_id", "insight_id"],
)

project_session_recordings_router.register(
    r"sharing",
    sharing.SharingConfigurationViewSet,
    "project_recording_sharing",
    ["team_id", "recording_id"],
)

projects_router.register(
    r"notebooks",
    notebook.NotebookViewSet,
    "project_notebooks",
    ["team_id"],
)

projects_router.register(
    r"error_tracking/symbol_sets",
    error_tracking.ErrorTrackingSymbolSetViewSet,
    "project_error_tracking_symbol_set",
    ["team_id"],
)

projects_router.register(
    r"error_tracking/issue",
    error_tracking.ErrorTrackingIssueViewSet,
    "project_error_tracking_issue",
    ["team_id"],
)

projects_router.register(
    r"error_tracking/stack_frames",
    error_tracking.ErrorTrackingStackFrameViewSet,
    "project_error_tracking_stack_frames",
    ["team_id"],
)

projects_router.register(
    r"user_groups",
    user_group.UserGroupViewSet,
    "project_user_groups",
    ["team_id"],
)

projects_router.register(
    r"comments",
    comments.CommentViewSet,
    "project_comments",
    ["team_id"],
)

projects_router.register(
    r"hog_functions",
    hog_function.HogFunctionViewSet,
    "project_hog_functions",
    ["team_id"],
)

projects_router.register(
    r"hog_function_templates",
    hog_function_template.PublicHogFunctionTemplateViewSet,
    "project_hog_function_templates",
    ["team_id"],
)

projects_router.register(
    r"hog",
    hog.HogViewSet,
    "hog",
    ["team_id"],
)

projects_router.register(
    r"metalytics",
    metalytics.MetalyticsViewSet,
    "project_metalytics",
    ["team_id"],
)

projects_router.register(
    r"insight_variables",
    insight_variable.InsightVariableViewSet,
    "project_insight_variables",
    ["team_id"],
)

projects_router.register(
    r"alerts",
    alert.AlertViewSet,
    "project_alerts",
    ["team_id"],
)

projects_router.register(r"search", search.SearchViewSet, "project_search", ["team_id"])

projects_router.register(
    r"data_color_themes", data_color_theme.DataColorThemeViewSet, "project_data_color_themes", ["team_id"]
)

projects_router.register(
    r"web_vitals",
    web_vitals.WebVitalsViewSet,
    "project_web_vitals",
    ["team_id"],
)

router.register(r"wizard", wizard.SetupWizardViewSet, "wizard")

projects_router.register(
    r"data_modeling_jobs",
    data_modeling_job.DataModelingJobViewSet,
    "project_data_modeling_jobs",
    ["team_id"],
)
