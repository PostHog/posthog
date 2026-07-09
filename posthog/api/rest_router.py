import importlib
import importlib.util

from django.apps import apps

from rest_framework import decorators, exceptions, viewsets
from rest_framework_extensions.routers import NestedRegistryItem

# Preload to work around circular imports in `ee.hogai.{core.agent_modes,chat_agent,tools}`.
import posthog.temporal.ai  # noqa: F401
from posthog.api import data_color_theme, metalytics, my_notifications, project, user_integration, user_push_token
from posthog.api.csp_reporting import CSPReportingViewSet
from posthog.api.js_snippet import JsSnippetViewSet
from posthog.api.product_enablement import ProductEnablementViewSet
from posthog.api.query_performance_proxy import QueryPerformanceProxyViewSet
from posthog.api.routing import DefaultRouterPlusPlus, RouterRegistry
from posthog.api.sdk_health import SdkHealthViewSet
from posthog.api.wizard import http as wizard
from posthog.settings import EE_AVAILABLE

from ee.api.quota_limits import QuotaLimitsViewSet
from ee.api.session_summaries import SessionGroupSummaryViewSet, SingleSessionSummaryViewSet
from ee.api.vercel import vercel_installation, vercel_product, vercel_proxy, vercel_resource

from ..session_recordings.session_recording_api import SessionRecordingViewSet
from ..session_recordings.session_recording_external_reference_api import SessionRecordingExternalReferenceViewSet
from ..session_recordings.session_recording_playlist_api import SessionRecordingPlaylistViewSet
from ..taxonomy import property_definition_api
from . import (
    advanced_activity_logs,
    async_migration,
    authentication,
    cimd_verification_token,
    cli_auth,
    comments,
    dead_letter_queue,
    debug_ch_queries,
    event_definition,
    event_schema,
    health_issue,
    hog,
    identity_provider_config,
    ingestion_warnings,
    ingestion_warnings_v2,
    instance_settings,
    instance_status,
    integration,
    object_media_preview,
    organization,
    organization_domain,
    organization_integration,
    organization_invite,
    organization_member,
    organization_personal_api_key,
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
from .file_system import file_system, file_system_shortcut, user_product_list
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

# Nested endpoints shared
projects_router = routers.add("projects", router.register(r"projects", project.RootProjectViewSet, "projects"))
projects_router.register(r"environments", team.ProjectEnvironmentsViewSet, "project_environments", ["project_id"])
environments_router = routers.add(
    "environments", router.register(r"environments", team.RootTeamViewSet, "environments")
)


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


projects_router.register(r"sdk_health", SdkHealthViewSet, "project_sdk_health", ["project_id"])
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

# Tasks endpoints

# PostHog Code invites (not project-scoped)

# Seats (proxied to billing service)

# Quota limits (project-scoped — backs the LLM gateway's QuotaResolver)
projects_router.register(
    r"quota_limits",
    QuotaLimitsViewSet,
    "project_quota_limits",
    ["team_id"],
)
# Self-driving turns products ON (via the `products-enable` MCP tool) before enabling their
# signal sources. Gated by the narrow `product_enablement` scope, never `project:write`.
projects_router.register(
    r"product_enablement",
    ProductEnablementViewSet,
    "project_product_enablement",
    ["team_id"],
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
    r"integrations", integration.IntegrationViewSet, "environment_integrations", ["team_id"]
)
register_legacy_dual_route_team_nested_viewset(
    r"ingestion_warnings",
    ingestion_warnings.IngestionWarningsViewSet,
    "environment_ingestion_warnings",
    ["team_id"],
)

projects_router.register(
    r"ingestion_warnings_v2",
    ingestion_warnings_v2.IngestionWarningsV2ViewSet,
    "project_ingestion_warnings_v2",
    ["team_id"],
)


projects_router.register(
    r"data_management",
    DataManagementViewSet,
    "project_data_management",
    ["project_id"],
)


register_legacy_dual_route_team_nested_viewset(
    r"file_system", file_system.FileSystemViewSet, "environment_file_system", ["team_id"]
)

projects_router.register(
    r"desktop_file_system",
    file_system.DesktopFileSystemViewSet,
    "project_desktop_file_system",
    ["team_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"file_system_shortcut",
    file_system_shortcut.FileSystemShortcutViewSet,
    "environment_file_system_shortcut",
    ["team_id"],
)

projects_router.register(
    r"desktop_file_system_shortcut",
    file_system_shortcut.DesktopFileSystemShortcutViewSet,
    "project_desktop_file_system_shortcut",
    ["team_id"],
)


register_legacy_dual_route_team_nested_viewset(
    r"user_product_list",
    user_product_list.UserProductListViewSet,
    "environment_user_product_list",
    ["team_id"],
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
    r"identity_provider_configs",
    identity_provider_config.IdentityProviderConfigViewSet,
    "organization_identity_provider_configs",
    ["organization_id"],
)
organizations_router.register(
    r"personal_api_keys",
    organization_personal_api_key.OrganizationPersonalAPIKeyViewSet,
    "organization_personal_api_keys",
    ["organization_id"],
)
organizations_router.register(
    r"cimd_verification_tokens",
    cimd_verification_token.CIMDVerificationTokenViewSet,
    "organization_cimd_verification_tokens",
    ["organization_id"],
)
organizations_router.register(
    r"proxy_records",
    proxy_record.ProxyRecordViewset,
    "proxy_records",
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

# Legacy endpoints CH (to be removed eventually)
router.register(r"cohort", LegacyCohortViewSet, basename="cohort")
router.register(r"element", LegacyElementViewSet, basename="element")
router.register(r"event", LegacyEventViewSet, basename="event")

# Nested endpoints CH
register_legacy_dual_route_team_nested_viewset(r"events", EventViewSet, "environment_events", ["team_id"])
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
    from ee.clickhouse.views.groups import GroupsTypesViewSet, GroupsViewSet, GroupUsageMetricViewSet
    from ee.clickhouse.views.person import EnterprisePersonViewSet, LegacyEnterprisePersonViewSet

    register_legacy_dual_route_team_nested_viewset(r"groups", GroupsViewSet, "environment_groups", ["team_id"])
    group_types_router = projects_router.register(
        r"groups_types", GroupsTypesViewSet, "project_groups_types", ["project_id"]
    )
    group_types_router.register(
        r"metrics", GroupUsageMetricViewSet, "project_groups_metrics", ["project_id", "group_type_index"]
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
    register_legacy_dual_route_team_nested_viewset(r"persons", PersonViewSet, "environment_persons", ["team_id"])
    router.register(r"person", LegacyPersonViewSet, "persons")

# session_recordings sharing nest stays central — the session_recordings viewsets
# still live under posthog/session_recordings/ rather than in a product folder.
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
    r"session_group_summaries",
    SessionGroupSummaryViewSet,
    "project_session_group_summaries",
    ["project_id"],
)

projects_router.register(
    r"single_session_summaries",
    SingleSessionSummaryViewSet,
    "project_single_session_summaries",
    ["project_id"],
)

register_legacy_dual_route_team_nested_viewset(
    r"quick_filters",
    quick_filters.QuickFilterViewSet,
    "project_quick_filters",
    ["team_id"],
)


projects_router.register(
    r"comments",
    comments.CommentViewSet,
    "project_comments",
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


register_legacy_dual_route_team_nested_viewset(
    r"csp-reporting",
    CSPReportingViewSet,
    "project_csp_reporting",
    ["team_id"],
)


projects_router.register(r"js-snippet", JsSnippetViewSet, "project_js_snippet", ["team_id"])


register_legacy_dual_route_team_nested_viewset(
    r"core_events",
    CoreEventViewSet,
    "project_core_events",
    ["team_id"],
)


# --- Product route auto-discovery -----------------------------------------------------
# Every parent above (root + projects + environments + organizations) and all of core's
# own routes are registered before this loop. Migrated products then register themselves
# by exposing `register_routes(routers)` in `products/<name>/backend/routes.py`; the loop
# finds them via INSTALLED_APPS, so adding a product needs no edit here.
#
# Why a loop here, and why eager (not AppConfig.ready()):
#   - ROOT_URLCONF is imported lazily on first URL resolution, not during django.setup().
#     `posthog/urls.py` imports this module, so the whole API surface loads at first
#     request and never at boot — Celery workers and management commands that never
#     resolve a URL never import it. We keep that.
#   - ready()-based self-registration would run inside django.setup() in every process,
#     and registering a route imports its viewset class — so it would drag the entire
#     product API into setup() everywhere, regressing that laziness. Running the loop at
#     import of `posthog.api` (i.e. first request) keeps the API out of setup().
#   - Net: core still triggers registration (via the existing `posthog.api` import) rather
#     than products self-pushing — you can have "core imports nothing statically" OR "API
#     stays out of setup()", not both; we keep the API lazy.
#
# Order-independence: products only nest onto the four core-owned parents and never onto
# each other, and all parents exist before this loop, so iteration order does not affect
# the resolved route set. `RouterRegistry.add()` rejects product callers, making
# "parents stay core-owned" an enforced invariant rather than a convention.
#
# Accepted cost: routes are imported dynamically here, so the core->product import edges
# are not statically visible to import tooling (tach/grimp). Accepted on purpose — it
# removes the hand-maintained product list that duplicated PRODUCTS_APPS.
for _app_config in apps.get_app_configs():
    if not _app_config.name.startswith("products."):
        continue
    _routes_module = f"{_app_config.name}.routes"
    # find_spec (not try/except ImportError) so a real ImportError inside a routes.py
    # surfaces instead of being silently swallowed as "no routes module".
    if importlib.util.find_spec(_routes_module) is None:
        continue
    _register_routes = getattr(importlib.import_module(_routes_module), "register_routes", None)
    if callable(_register_routes):
        _register_routes(routers)
