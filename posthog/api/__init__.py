from rest_framework import decorators, exceptions, viewsets
from rest_framework_extensions.routers import NestedRegistryItem

# Preload to work around circular imports in `ee.hogai.{core.agent_modes,chat_agent,tools}`.
import posthog.temporal.ai  # noqa: F401
from posthog.api import data_color_theme, metalytics, my_notifications, project, user_integration, user_push_token
from posthog.api.batch_imports import BatchImportViewSet
from posthog.api.csp_reporting import CSPReportingViewSet
from posthog.api.js_snippet import JsSnippetViewSet
from posthog.api.query_performance_proxy import QueryPerformanceProxyViewSet
from posthog.api.routing import DefaultRouterPlusPlus, RouterRegistry
from posthog.api.sdk_doctor import SdkDoctorViewSet
from posthog.api.wizard import http as wizard
from posthog.approvals import api as approval_api
from posthog.batch_exports import http as batch_exports
from posthog.batch_exports.api import file_download
from posthog.settings import EE_AVAILABLE

import products.tasks.backend.api as tasks
import products.signals.backend.views as signals
import products.tasks.backend.seat_api as seats
import products.alerts.backend.api.alert as alert
from products.actions.backend.routes import register_routes as register_actions_routes
from products.ai_observability.backend.routes import register_routes as register_ai_observability_routes
from products.business_knowledge.backend.routes import register_routes as register_business_knowledge_routes
from products.cdp.backend.api import hog_function, hog_function_template, plugin, plugin_log_entry
from products.conversations.backend.routes import register_routes as register_conversations_routes
from products.customer_analytics.backend.routes import register_routes as register_customer_analytics_routes
from products.dashboards.backend.api import dashboard, dashboard_templates
from products.data_modeling.backend.routes import register_routes as register_data_modeling_routes
from products.data_warehouse.backend.routes import register_routes as register_data_warehouse_routes
from products.deployments.backend.routes import register_routes as register_deployments_routes
from products.desktop_recordings.backend.routes import register_routes as register_desktop_recordings_routes
from products.early_access_features.backend.routes import register_routes as register_early_access_features_routes
from products.endpoints.backend.routes import register_routes as register_endpoints_routes
from products.error_tracking.backend.routes import register_routes as register_error_tracking_routes
from products.feature_flags.backend.api import feature_flag, flag_value, organization_feature_flag, scheduled_change
from products.legal_documents.backend.routes import register_routes as register_legal_documents_routes
from products.links.backend.routes import register_routes as register_links_routes
from products.live_debugger.backend.routes import register_routes as register_live_debugger_routes
from products.logs.backend.routes import register_routes as register_logs_routes
from products.marketing_analytics.backend.routes import register_routes as register_marketing_analytics_routes
from products.mcp_store.backend.routes import register_routes as register_mcp_store_routes
from products.messaging.backend.routes import register_routes as register_messaging_routes
from products.metrics.backend.routes import register_routes as register_metrics_routes
from products.notebooks.backend.api.notebook import NotebookViewSet
from products.notifications.backend.routes import register_routes as register_notifications_routes
from products.posthog_ai.backend.routes import register_routes as register_posthog_ai_routes
from products.product_tours.backend.routes import register_routes as register_product_tours_routes
from products.replay_vision.backend.routes import register_routes as register_replay_vision_routes
from products.revenue_analytics.backend.routes import register_routes as register_revenue_analytics_routes
from products.signals.backend.views import SignalViewSet
from products.surveys.backend.routes import register_routes as register_survey_routes
from products.tracing.backend.routes import register_routes as register_tracing_routes
from products.user_interviews.backend.routes import register_routes as register_user_interviews_routes
from products.visual_review.backend.routes import register_routes as register_visual_review_routes
from products.web_analytics.backend.routes import register_routes as register_web_analytics_routes
from products.wizard.backend.routes import register_routes as register_wizard_routes
from products.workflows.backend.routes import register_routes as register_workflows_routes

from ee.api.quota_limits import QuotaLimitsViewSet
from ee.api.session_summaries import SessionGroupSummaryViewSet
from ee.api.vercel import vercel_installation, vercel_product, vercel_proxy, vercel_resource

from ..session_recordings.session_recording_api import SessionRecordingViewSet
from ..session_recordings.session_recording_external_reference_api import SessionRecordingExternalReferenceViewSet
from ..session_recordings.session_recording_playlist_api import SessionRecordingPlaylistViewSet
from ..taxonomy import property_definition_api
from . import (
    advanced_activity_logs,
    annotation,
    async_migration,
    authentication,
    cimd_verification_token,
    cli_auth,
    comments,
    dead_letter_queue,
    debug_ch_queries,
    event_definition,
    event_schema,
    exports,
    health_issue,
    hog,
    ingestion_warnings,
    instance_settings,
    instance_status,
    integration,
    materialized_column_slot,
    object_media_preview,
    organization,
    organization_domain,
    organization_integration,
    organization_invite,
    organization_member,
    personal_api_key,
    project_secret_api_key,
    proxy_record,
    query,
    quick_filters,
    resource_transfer,
    role_external_reference,
    schema_property_group,
    search,
    sharing,
    tagged_item,
    team,
    uploaded_media,
    user,
    user_home_settings,
    web_vitals,
    webauthn,
    welcome,
)
from .column_configuration import ColumnConfigurationViewSet
from .core_event import CoreEventViewSet
from .data_management import DataManagementViewSet
from .event_filter_config import EventFilterConfigViewSet
from .file_system import file_system, file_system_shortcut, persisted_folder, user_product_list
from .llm_prompt import LLMPromptViewSet
from .oauth import OrganizationOAuthApplicationViewSet
from .session import SessionViewSet


@decorators.api_view(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@decorators.authentication_classes([])
@decorators.permission_classes([])
def api_not_found(request):
    raise exceptions.NotFound(detail="Endpoint not found.")


router = DefaultRouterPlusPlus()
# Shared router handles, addressable by name, that products nest onto from their own
# `register_routes(routers)`. See posthog/api/routing.py:RouterRegistry.
routers = RouterRegistry()
routers.set_root(router)

# Legacy endpoints shared (to be removed eventually)
router.register(r"dashboard", dashboard.LegacyDashboardsViewSet, "legacy_dashboards")  # Should be completely unused now
router.register(
    r"dashboard_item", dashboard.LegacyInsightViewSet, "legacy_insights"
)  # To be deleted - unified into insight viewset
router.register(r"plugin_config", plugin.LegacyPluginConfigViewSet, "legacy_plugin_configs")

router.register(r"feature_flag", feature_flag.LegacyFeatureFlagViewSet)  # Used for library side feature flag evaluation
# Nested endpoints shared
projects_router = routers.add("projects", router.register(r"projects", project.RootProjectViewSet, "projects"))
projects_router.register(r"environments", team.ProjectEnvironmentsViewSet, "project_environments", ["project_id"])
environments_router = routers.add(
    "environments", router.register(r"environments", team.RootTeamViewSet, "environments")
)
register_visual_review_routes(routers)
register_user_interviews_routes(routers)
register_replay_vision_routes(routers)
project_notebooks_router = projects_router.register(r"notebooks", NotebookViewSet, "project_notebooks", ["project_id"])
register_early_access_features_routes(routers)
register_customer_analytics_routes(routers)
register_data_warehouse_routes(routers)
register_ai_observability_routes(routers)
# mcp_store registers a root-level route plus dual project/environment routes, so it
# runs here once the projects + environments parents exist.
register_mcp_store_routes(routers)


def register_legacy_dual_route_team_nested_viewset(
    prefix: str, viewset: type[viewsets.GenericViewSet], basename: str, parents_query_lookups: list[str]
) -> tuple[NestedRegistryItem, NestedRegistryItem]:
    """
    Register a team-nested viewset under BOTH /api/projects/:team_id/ and
    /api/environments/:team_id/, for endpoints whose dual-route surface needs
    to be preserved for existing clients.

    Background: PostHog briefly split projects and environments as separate
    concepts then rolled the split back. /api/projects/ is the canonical path;
    /api/environments/ is preserved only for clients that integrated against it
    during the split (SDKs, customer integrations), and gets auto-marked
    `deprecated: true` in the generated OpenAPI schema by the postprocess hook
    in posthog.api.documentation whenever a matching /api/projects/ route
    exists. That deprecation flag is what makes Orval pick the project route
    as canonical for the generated TypeScript client.

    The `basename` argument encodes which side was the original canonical one,
    which matters for stable URL-reverse names:
      • `project_<X>`     — project is canonical; env is a back-compat alias.
                            Pass this for endpoints that were (re-)introduced
                            env-only after the rollback by mistake.
      • `environment_<X>` — env was the canonical surface from the split era;
                            project alias is back-filled. Pass this for legacy
                            env-canonical endpoints.
    Either way, the project URL ends up with basename `project_<X>` and the env
    URL with `environment_<X>`.

    DO NOT USE FOR NEW ENDPOINTS. New team-nested endpoints should register
    directly under projects_router with no env alias — `# nosemgrep` markers
    around env registrations are the smell to look for in code review; this
    helper is the smell to look for in PRs that *add* registrations.

    Returns (project_nested, environment_nested).
    """
    return routers.register_legacy_dual_route(prefix, viewset, basename, parents_query_lookups)


legacy_project_plugins_configs_router, environment_plugins_configs_router = (
    register_legacy_dual_route_team_nested_viewset(
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
register_legacy_dual_route_team_nested_viewset(
    r"pipeline_transformation_configs",
    plugin.PipelineTransformationsConfigsViewSet,
    "environment_pipeline_transformation_configs",
    ["team_id"],
)
register_legacy_dual_route_team_nested_viewset(
    r"pipeline_destination_configs",
    plugin.PipelineDestinationsConfigsViewSet,
    "environment_pipeline_destination_configs",
    ["team_id"],
)
register_legacy_dual_route_team_nested_viewset(
    r"pipeline_frontend_apps_configs",
    plugin.PipelineFrontendAppsConfigsViewSet,
    "environment_pipeline_frontend_apps_configs",
    ["team_id"],
)
register_legacy_dual_route_team_nested_viewset(
    r"pipeline_import_apps_configs",
    plugin.PipelineImportAppsConfigsViewSet,
    "environment_pipeline_import_apps_configs",
    ["team_id"],
)

projects_router.register(r"annotations", annotation.AnnotationsViewSet, "project_annotations", ["project_id"])
projects_router.register(r"sdk_doctor", SdkDoctorViewSet, "project_sdk_doctor", ["project_id"])
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
    "project_my_notifications",
    ["project_id"],
)
project_feature_flags_router = projects_router.register(
    r"feature_flags",
    feature_flag.FeatureFlagViewSet,
    "project_feature_flags",
    ["project_id"],
)
register_wizard_routes(routers)
register_deployments_routes(routers)

# Tasks endpoints
project_tasks_router = projects_router.register(r"tasks", tasks.TaskViewSet, "project_tasks", ["team_id"])
project_tasks_router.register(r"runs", tasks.TaskRunViewSet, "project_task_runs", ["team_id", "task_id"])
projects_router.register(r"task_automations", tasks.TaskAutomationViewSet, "project_task_automations", ["team_id"])
projects_router.register(
    r"sandbox_environments",
    tasks.SandboxEnvironmentViewSet,
    "project_sandbox_environments",
    ["team_id"],
)

# PostHog Code invites (not project-scoped)
router.register(r"code/invites", tasks.CodeInviteViewSet, "code_invites")

# Seats (proxied to billing service)
router.register(r"seats", seats.SeatViewSet, "seats")

# Quota limits (project-scoped — backs the LLM gateway's QuotaResolver)
projects_router.register(
    r"quota_limits",
    QuotaLimitsViewSet,
    "project_quota_limits",
    ["team_id"],
)

# Surveys registers its own routes from products/surveys/backend/routes.py (pilot for
# product-local route registration via RouterRegistry).
register_survey_routes(routers)
register_product_tours_routes(routers)
projects_router.register(
    r"dashboard_templates",
    dashboard_templates.DashboardTemplateViewSet,
    "project_dashboard_templates",
    ["project_id"],
)
legacy_project_dashboards_router, environment_dashboards_router = register_legacy_dual_route_team_nested_viewset(
    r"dashboards", dashboard.DashboardsViewSet, "environment_dashboards", ["team_id"]
)

register_legacy_dual_route_team_nested_viewset(
    r"column_configurations",
    ColumnConfigurationViewSet,
    "project_column_configurations",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"event_filter",
    EventFilterConfigViewSet,
    "project_event_filter",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"health_issues",
    health_issue.HealthIssueViewSet,
    "project_health_issues",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"llm_prompts",
    LLMPromptViewSet,
    "project_llm_prompts",
    ["team_id"],
)


register_legacy_dual_route_team_nested_viewset(
    r"exports", exports.ExportedAssetViewSet, "environment_exports", ["team_id"]
)
register_legacy_dual_route_team_nested_viewset(
    r"integrations", integration.IntegrationViewSet, "environment_integrations", ["team_id"]
)
register_legacy_dual_route_team_nested_viewset(
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

register_legacy_dual_route_team_nested_viewset(
    r"materialized_column_slots",
    materialized_column_slot.MaterializedColumnSlotViewSet,
    "project_materialized_column_slots",
    ["team_id"],
)

projects_router.register(
    r"scheduled_changes",
    scheduled_change.ScheduledChangeViewSet,
    "project_scheduled_changes",
    ["project_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"file_system", file_system.FileSystemViewSet, "environment_file_system", ["team_id"]
)

register_legacy_dual_route_team_nested_viewset(
    r"file_system_shortcut",
    file_system_shortcut.FileSystemShortcutViewSet,
    "environment_file_system_shortcut",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"persisted_folder",
    persisted_folder.PersistedFolderViewSet,
    "environment_persisted_folder",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"user_product_list",
    user_product_list.UserProductListViewSet,
    "environment_user_product_list",
    ["team_id"],
)

legacy_project_batch_exports_router, environment_batch_exports_router = register_legacy_dual_route_team_nested_viewset(
    r"batch_exports", batch_exports.BatchExportViewSet, "environment_batch_exports", ["team_id"]
)

register_legacy_dual_route_team_nested_viewset(
    r"file_download_batch_exports",
    file_download.FileDownloadBatchExportOnDemandViewSet,
    "environment_file_download_batch_exports",
    ["team_id"],
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

projects_router.register(
    r"object_media_previews",
    object_media_preview.ObjectMediaPreviewViewSet,
    "project_object_media_previews",
    ["project_id"],
)

projects_router.register(r"tags", tagged_item.TaggedItemViewSet, "project_tags", ["project_id"])
register_legacy_dual_route_team_nested_viewset(r"query", query.QueryViewSet, "environment_query", ["team_id"])

# External data resources

register_data_modeling_routes(routers)

register_notifications_routes(routers)

# Organizations nested endpoints
organizations_router = routers.add(
    "organizations", router.register(r"organizations", organization.OrganizationViewSet, "organizations")
)
organizations_router.register(r"projects", project.ProjectViewSet, "organization_projects", ["organization_id"])
organizations_router.register(
    r"integrations",
    organization_integration.OrganizationIntegrationViewSet,
    "organization_integrations",
    ["organization_id"],
)
organizations_router.register(
    r"oauth_applications",
    OrganizationOAuthApplicationViewSet,
    "organization_oauth_applications",
    ["organization_id"],
)
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
    r"cimd_verification_tokens",
    cimd_verification_token.CIMDVerificationTokenViewSet,
    "organization_cimd_verification_tokens",
    ["organization_id"],
)
register_legal_documents_routes(routers)
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
organizations_router.register(
    r"resource_transfers",
    resource_transfer.ResourceTransferViewSet,
    "organization_resource_transfers",
    ["organization_id"],
)
organizations_router.register(
    r"role_external_references",
    role_external_reference.RoleExternalReferenceViewSet,
    "organization_role_external_references",
    ["organization_id"],
)
organizations_router.register(
    r"welcome",
    welcome.WelcomeViewSet,
    "organization_welcome",
    ["organization_id"],
)
organizations_router.register(
    r"advanced_activity_logs",
    advanced_activity_logs.OrganizationAdvancedActivityLogsViewSet,
    "organization_advanced_activity_logs",
    ["organization_id"],
)

# General endpoints (shared across CH & PG)
router.register(r"login", authentication.LoginViewSet, "login")
router.register(r"login/dev", authentication.DevLoginViewSet, "login_dev")
router.register(r"login/token", authentication.TwoFactorViewSet, "login_token")
router.register(r"login/precheck", authentication.LoginPrecheckViewSet, "login_precheck")
router.register(r"login/email-mfa", authentication.EmailMFAViewSet, "login_email_mfa")
router.register(r"login/2fa/passkey", authentication.TwoFactorPasskeyViewSet, "login_2fa_passkey")
router.register(r"webauthn/register", webauthn.WebAuthnRegistrationViewSet, "webauthn_register")
router.register(r"webauthn/signup-register", webauthn.WebAuthnSignupRegistrationViewSet, "webauthn_signup_register")
router.register(r"webauthn/login", webauthn.WebAuthnLoginViewSet, "webauthn_login")
router.register(r"webauthn/credentials", webauthn.WebAuthnCredentialViewSet, "webauthn_credentials")
router.register(r"reset", authentication.PasswordResetViewSet, "password_reset")
users_router = router.register(r"users", user.UserViewSet, "users")
users_router.register(
    r"integrations",
    user_integration.UserIntegrationViewSet,
    "user_integration",
    ["uuid"],
)
users_router.register(
    r"push_tokens",
    user_push_token.UserPushTokenViewSet,
    "user_push_token",
    ["uuid"],
)
router.register(
    r"user_home_settings",
    user_home_settings.UserHomeSettingsViewSet,
    "user_home_settings",
)
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
router.register(r"cli-auth", cli_auth.CLIAuthViewSet, "cli_auth")
router.register(r"instance_status", instance_status.InstanceStatusViewSet, "instance_status")
router.register(r"dead_letter_queue", dead_letter_queue.DeadLetterQueueViewSet, "dead_letter_queue")
router.register(r"async_migrations", async_migration.AsyncMigrationsViewset, "async_migrations")
router.register(r"instance_settings", instance_settings.InstanceSettingsViewset, "instance_settings")
router.register(r"debug_ch_queries", debug_ch_queries.DebugCHQueries, "debug_ch_queries")
router.register(r"query_performance_proxy", QueryPerformanceProxyViewSet, "query_performance_proxy")

from posthog.api.cohort import CohortViewSet, LegacyCohortViewSet  # noqa: E402
from posthog.api.element import ElementViewSet, LegacyElementViewSet  # noqa: E402
from posthog.api.event import EventViewSet, LegacyEventViewSet  # noqa: E402
from posthog.api.person import LegacyPersonViewSet, PersonViewSet  # noqa: E402
from posthog.api.web_experiment import WebExperimentViewSet  # noqa: E402

from products.product_analytics.backend.api.insight import InsightViewSet  # noqa: E402
from products.product_analytics.backend.api.insight_variable import InsightVariableViewSet  # noqa: E402

# Legacy endpoints CH (to be removed eventually)
router.register(r"cohort", LegacyCohortViewSet, basename="cohort")
router.register(r"element", LegacyElementViewSet, basename="element")
register_web_analytics_routes(routers)
router.register(r"event", LegacyEventViewSet, basename="event")

# Nested endpoints CH
register_legacy_dual_route_team_nested_viewset(r"events", EventViewSet, "environment_events", ["team_id"])
register_actions_routes(routers)
projects_router.register(r"web_experiments", WebExperimentViewSet, "web_experiments", ["project_id"])
projects_router.register(r"cohorts", CohortViewSet, "project_cohorts", ["project_id"])

register_legacy_dual_route_team_nested_viewset(
    r"elements",
    ElementViewSet,
    "environment_elements",
    ["team_id"],  # TODO: Can be removed?
)

legacy_project_session_recordings_router, environment_sessions_recordings_router = (
    register_legacy_dual_route_team_nested_viewset(
        r"session_recordings",
        SessionRecordingViewSet,
        "environment_session_recordings",
        ["team_id"],
    )
)

register_legacy_dual_route_team_nested_viewset(
    r"session_recording_external_references",
    SessionRecordingExternalReferenceViewSet,
    "project_session_recording_external_references",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"session_recording_playlists",
    SessionRecordingPlaylistViewSet,
    "environment_session_recording_playlist",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(r"sessions", SessionViewSet, "environment_sessions", ["team_id"])

if EE_AVAILABLE:
    from products.experiments.backend.presentation.views import EnterpriseExperimentsViewSet

    from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutViewSet
    from ee.clickhouse.views.experiment_saved_metrics import ExperimentSavedMetricViewSet
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
    register_legacy_dual_route_team_nested_viewset(r"groups", GroupsViewSet, "environment_groups", ["team_id"])
    group_types_router = projects_router.register(
        r"groups_types", GroupsTypesViewSet, "project_groups_types", ["project_id"]
    )
    group_types_router.register(
        r"metrics", GroupUsageMetricViewSet, "project_groups_metrics", ["project_id", "group_type_index"]
    )
    legacy_project_insights_router, environment_insights_router = register_legacy_dual_route_team_nested_viewset(
        r"insights", EnterpriseInsightsViewSet, "environment_insights", ["team_id"]
    )
    register_legacy_dual_route_team_nested_viewset(
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
    router.register(
        r"vercel/proxy",
        vercel_proxy.VercelProxyViewSet,
        "vercel_proxy",
    )

else:
    legacy_project_insights_router, environment_insights_router = register_legacy_dual_route_team_nested_viewset(
        r"insights", InsightViewSet, "environment_insights", ["team_id"]
    )
    register_legacy_dual_route_team_nested_viewset(r"persons", PersonViewSet, "environment_persons", ["team_id"])
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


project_notebooks_router.register(
    r"sharing",
    sharing.SharingConfigurationViewSet,
    "project_notebook_sharing",
    ["project_id", "notebook_id"],
)

projects_router.register(
    r"session_group_summaries",
    SessionGroupSummaryViewSet,
    "project_session_group_summaries",
    ["project_id"],
)

register_error_tracking_routes(routers)


register_legacy_dual_route_team_nested_viewset(
    r"signals",
    SignalViewSet,
    "project_signals",
    ["team_id"],
)
signal_reports_router = projects_router.register(
    r"signals/reports",
    signals.SignalReportViewSet,
    "environment_signal_reports",
    ["team_id"],
)
signal_reports_router.register(
    r"tasks",
    signals.SignalReportTaskViewSet,
    "environment_signal_report_tasks",
    ["team_id", "report_id"],
)
signal_reports_router.register(
    r"artefacts",
    signals.SignalReportArtefactViewSet,
    "environment_signal_report_artefacts",
    ["team_id", "report_id"],
)
projects_router.register(
    r"signals/source_configs",
    signals.SignalSourceConfigViewSet,
    "environment_signal_source_configs",
    ["team_id"],
)
projects_router.register(
    r"signals/config",
    signals.SignalTeamConfigViewSet,
    "environment_signal_config",
    ["team_id"],
)
projects_router.register(
    r"signals/processing",
    signals.SignalProcessingViewSet,
    "environment_signal_processing",
    ["team_id"],
)

# Signals agent HTTP surface — exposed via MCP as `signals-scout-*` tools. Reads (runs,
# memory, project profile) are public-grantable via `signal_scout:read`; writes (findings,
# memory create/delete) are sandbox-scope only via `signal_scout_internal:write`, which
# lives in `INTERNAL_API_SCOPE_OBJECTS` and so is not selectable in the personal-API-key UI.
from products.signals.backend.scout_harness.views import (  # noqa: E402
    SignalProjectProfileViewSet,
    SignalScoutRunViewSet,
    SignalScratchpadViewSet,
)

projects_router.register(
    r"signals/scout/runs",
    SignalScoutRunViewSet,
    "environment_signals_scout_runs",
    ["team_id"],
)
projects_router.register(
    r"signals/scout/scratchpad",
    SignalScratchpadViewSet,
    "environment_signals_scout_scratchpad",
    ["team_id"],
)
projects_router.register(
    r"signals/scout/project_profile",
    SignalProjectProfileViewSet,
    "environment_signals_scout_project_profile",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"quick_filters",
    quick_filters.QuickFilterViewSet,
    "project_quick_filters",
    ["team_id"],
)

register_live_debugger_routes(routers)

projects_router.register(
    r"comments",
    comments.CommentViewSet,
    "project_comments",
    ["project_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"hog_functions",
    hog_function.HogFunctionViewSet,
    "environment_hog_functions",
    ["team_id"],
)

register_workflows_routes(routers)

register_links_routes(routers)

register_business_knowledge_routes(routers)

register_conversations_routes(routers)

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

register_legacy_dual_route_team_nested_viewset(
    r"metalytics",
    metalytics.MetalyticsViewSet,
    "environment_metalytics",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"insight_variables",
    InsightVariableViewSet,
    "environment_insight_variables",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"alerts",
    alert.AlertViewSet,
    "environment_alerts",
    ["team_id"],
)

projects_router.register(r"search", search.SearchViewSet, "project_search", ["project_id"])

register_legacy_dual_route_team_nested_viewset(
    r"project_secret_api_keys",
    project_secret_api_key.ProjectSecretAPIKeyViewSet,
    "environment_project_secret_api_keys",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"data_color_themes", data_color_theme.DataColorThemeViewSet, "environment_data_color_themes", ["team_id"]
)

register_legacy_dual_route_team_nested_viewset(
    r"web_vitals",
    web_vitals.WebVitalsViewSet,
    "project_web_vitals",
    ["team_id"],
)

router.register(r"wizard", wizard.SetupWizardViewSet, "wizard")


register_messaging_routes(routers)

# Logs endpoints
register_logs_routes(routers)

# Metrics endpoints
register_metrics_routes(routers)

register_endpoints_routes(routers)


register_tracing_routes(routers)

register_desktop_recordings_routes(routers)

register_legacy_dual_route_team_nested_viewset(
    r"csp-reporting",
    CSPReportingViewSet,
    "project_csp_reporting",
    ["team_id"],
)

register_marketing_analytics_routes(routers)

register_revenue_analytics_routes(routers)

projects_router.register(
    r"flag_value",
    flag_value.FlagValueViewSet,
    "project_flag_value",
    ["project_id"],
)

projects_router.register(r"js-snippet", JsSnippetViewSet, "project_js_snippet", ["team_id"])


register_legacy_dual_route_team_nested_viewset(
    r"change_requests",
    approval_api.ChangeRequestViewSet,
    "project_change_requests",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"approval_policies",
    approval_api.ApprovalPolicyViewSet,
    "project_approval_policies",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"core_events",
    CoreEventViewSet,
    "project_core_events",
    ["team_id"],
)

register_posthog_ai_routes(routers)
