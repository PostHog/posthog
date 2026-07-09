# Web app specific settings/middleware/apps setup
import os
from datetime import timedelta

import structlog
from corsheaders.defaults import default_headers

from posthog.scopes import get_scope_descriptions
from posthog.settings.base_variables import BASE_DIR, CLOUD_DEPLOYMENT, DEBUG, TEST
from posthog.settings.utils import generate_rsa_private_key_pem, get_from_env, get_list, str_to_bool
from posthog.utils_cors import CORS_ALLOWED_TRACING_HEADERS

logger = structlog.get_logger(__name__)

####
# django-axes

# lockout after too many attempts
AXES_ENABLED = get_from_env("AXES_ENABLED", not TEST, type_cast=str_to_bool)
AXES_HANDLER = "axes.handlers.cache.AxesCacheHandler"
AXES_FAILURE_LIMIT = get_from_env("AXES_FAILURE_LIMIT", 30, type_cast=int)
AXES_COOLOFF_TIME = timedelta(minutes=10)
AXES_LOCKOUT_CALLABLE = "posthog.api.authentication.axes_locked_out"
AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]
# Keep legacy 403 status code for lockouts (django-axes 6.0+ defaults to 429)
AXES_HTTP_RESPONSE_CODE = 403

####
# Application definition

# TODO: Automatically generate these like we do for the frontend
# NOTE: Add these definitions here and on `tach.toml`
PRODUCTS_APPS = [
    "products.analytics_platform.backend.apps.AnalyticsPlatformConfig",
    "products.early_access_features.backend.apps.EarlyAccessFeaturesConfig",
    "products.tasks.backend.apps.TasksConfig",
    "products.links.backend.apps.LinksConfig",
    "products.field_notes.backend.apps.FieldNotesConfig",
    "products.revenue_analytics.backend.apps.RevenueAnalyticsConfig",
    "products.user_interviews.backend.apps.UserInterviewsConfig",
    "products.ai_observability.backend.apps.AIObservabilityConfig",
    "products.ai_gateway.backend.apps.AIGatewayConfig",
    "products.llm_analytics.backend.apps.LlmAnalyticsConfig",
    "products.skills.backend.apps.SkillsConfig",
    "products.endpoints.backend.apps.EndpointsConfig",
    "products.marketing_analytics.backend.apps.MarketingAnalyticsConfig",
    "products.error_tracking.backend.apps.ErrorTrackingConfig",
    "products.notebooks.backend.apps.NotebooksConfig",
    "products.surveys.backend.apps.SurveysConfig",
    "products.data_warehouse.backend.apps.DataWarehouseConfig",
    "products.data_modeling.backend.apps.DataModelingConfig",
    "products.live_debugger.backend.apps.LiveDebuggerConfig",
    "products.experiments.backend.apps.ExperimentsConfig",
    "products.feature_flags.backend.apps.FeatureFlagsConfig",
    "products.customer_analytics.backend.apps.CustomerAnalyticsConfig",
    "products.conversations.backend.apps.ConversationsConfig",
    "products.slack_app.backend.apps.SlackAppConfig",
    "products.product_tours.backend.apps.ProductToursConfig",
    "products.workflows.backend.apps.WorkflowsConfig",
    "products.cdp.backend.apps.CdpConfig",
    "products.posthog_ai.backend.apps.PosthogAiConfig",
    "products.signals.backend.apps.SignalsConfig",
    "products.visual_review.backend.apps.VisualReviewConfig",
    "products.replay_vision.backend.apps.ReplayVisionConfig",
    "products.mcp_store.backend.apps.McpStoreConfig",
    "products.event_definitions.backend.apps.EventDefinitionsConfig",
    "products.logs.backend.apps.LogsConfig",
    "products.tracing.backend.apps.TracingConfig",
    "products.metrics.backend.apps.MetricsConfig",
    "products.notifications.backend.apps.NotificationsConfig",
    "products.dashboards.backend.apps.DashboardsConfig",
    "products.messaging.backend.apps.MessagingConfig",
    "products.mcp_analytics.backend.apps.McpAnalyticsConfig",
    "products.platform_features.backend.apps.PlatformFeaturesConfig",
    "products.streamlit_apps.backend.apps.StreamlitAppsConfig",
    "products.legal_documents.backend.apps.LegalDocumentsConfig",
    "products.access_control.backend.apps.AccessControlConfig",
    "products.warehouse_sources_queue.backend.apps.WarehouseSourcesQueueConfig",
    "products.business_knowledge.backend.apps.BusinessKnowledgeConfig",
    "products.agent_platform.backend.apps.AgentPlatformConfig",
    "products.web_analytics.backend.apps.WebAnalyticsConfig",
    "products.warehouse_sources.backend.apps.WarehouseSourcesConfig",
    "products.data_tools.backend.apps.DataToolsConfig",
    "products.alerts.backend.apps.AlertsConfig",
    "products.actions.backend.apps.ActionsConfig",
    "products.product_analytics.backend.apps.ProductAnalyticsConfig",
    "products.wizard.backend.apps.WizardConfig",
    "products.exports.backend.apps.ExportsConfig",
    "products.annotations.backend.apps.AnnotationsConfig",
    "products.batch_exports.backend.apps.BatchExportsConfig",
    "products.engineering_analytics.backend.apps.EngineeringAnalyticsConfig",
    "products.managed_migrations.backend.apps.ManagedMigrationsConfig",
    "products.replay.backend.apps.ReplayConfig",
    "products.cohorts.backend.apps.CohortsConfig",
    "products.growth.backend.apps.GrowthConfig",
    "products.reminders.backend.apps.RemindersConfig",
    "products.approvals.backend.apps.ApprovalsConfig",
]

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",  # makes sure that whitenoise handles static files in development
    # `SimpleAdminConfig` skips Django's eager `autodiscover_modules('admin')` at
    # startup. We invoke autodiscover ourselves from `register_all_admin()` (called
    # lazily via `LazyAdminRegistry` on first `admin.site._registry` access), which
    # keeps every product/admin import out of `django.setup()`.
    "django.contrib.admin.apps.SimpleAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    # Replaces django.contrib.sessions: a custom session model on the same django_session table
    # (see posthog/session). SessionMiddleware still works without the contrib app installed.
    "posthog.session",
    "django.contrib.messages",
    "django.contrib.postgres",
    "django.contrib.staticfiles",
    "posthog.apps.PostHogConfig",
    "rest_framework",
    "loginas",
    "corsheaders",
    "social_django",
    "django_filters",
    "axes",
    "django_structlog",
    "drf_spectacular",
    *PRODUCTS_APPS,
    "django_otp",
    "django_otp.plugins.otp_static",
    "django_otp.plugins.otp_totp",
    # 'django_otp.plugins.otp_email',  # <- if you want email capability.
    # See above for automatically generated apps for all of our products
    "two_factor",
    # 'two_factor.plugins.phonenumber',  # <- if you want phone number capability.
    # 'two_factor.plugins.email',  # <- if you want email capability.
    # 'two_factor.plugins.yubikey',  # <- for yubikey capability.
    "oauth2_provider",
    "django_admin_inline_paginator",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "posthog.gzip_middleware.ScopedGZipMiddleware",
    "posthog.middleware.per_request_logging_context_middleware",
    "django_structlog.middlewares.RequestMiddleware",
    "posthog.middleware.Fix204Middleware",
    "django.middleware.security.SecurityMiddleware",
    "posthog.middleware.OAuthCoopMiddleware",
    # NOTE: we need healthcheck high up to avoid hitting middlewares that may be
    # using dependencies that the healthcheck should be checking. It should be
    # ok below the above middlewares however.
    "posthog.health.healthcheck_middleware",
    "posthog.middleware.ShortCircuitMiddleware",
    "posthog.middleware.AllowIPMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "posthog.middleware.OAuthCorsPreflightMiddleware",  # Must precede CorsMiddleware — echoes custom headers on OAuth preflights
    "corsheaders.middleware.CorsMiddleware",
    "posthog.middleware.CSPMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Below CorsMiddleware so responses get CORS headers; above auth/CSRF and URL
    # resolution so the /api/environments → /api/projects rewrite is in place before the
    # request is routed and authenticated.
    "posthog.middleware.EnvironmentsRewriteMiddleware",
    "posthog.middleware.CsrfOrKeyViewMiddleware",
    "posthog.middleware.QueryTimeCountingMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Must run immediately after AuthenticationMiddleware so downstream middleware
    # (activity logging, structlog binding, etc.) sees the swapped staff user on /admin/* paths.
    "posthog.middleware.AdminImpersonationMiddleware",
    "posthog.api.query_coalescer.QueryCoalescingMiddleware",
    "posthog.middleware.SocialAuthExceptionMiddleware",
    "posthog.middleware.SessionAgeMiddleware",
    "posthog.middleware.KnownLoginDeviceCookieMiddleware",
    "posthog.session.middleware.UserAuthSessionActivityMiddleware",
    "posthog.session.middleware.SessionRiskMiddleware",
    "posthog.middleware.ActivityLoggingMiddleware",
    "posthog.middleware.user_logging_context_middleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "posthog.middleware.AutoLogoutImpersonateMiddleware",
    "posthog.middleware.ImpersonationReadOnlyMiddleware",
    "posthog.middleware.ImpersonationBlockedPathsMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "posthog.middleware.ActiveOrganizationMiddleware",
    "posthog.middleware.CsvNeverCacheMiddleware",
    "axes.middleware.AxesMiddleware",
    "posthog.middleware.AutoProjectMiddleware",
    "posthog.middleware.CHQueries",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
    "posthog.middleware.PostHogTokenCookieMiddleware",
    "posthoganalytics.integrations.django.PosthogContextMiddleware",
]

DJANGO_STRUCTLOG_CELERY_ENABLED = True

if DEBUG:
    # rebase_migration command
    INSTALLED_APPS.append("django_linear_migrations")

# Append Enterprise Edition as an app if available
try:
    from ee.apps import EnterpriseConfig  # noqa: F401
except ImportError:
    pass
else:
    INSTALLED_APPS.append("ee.apps.EnterpriseConfig")

# Use django-extensions if it exists
try:
    import django_extensions  # noqa: F401
except ImportError:
    pass
else:
    INSTALLED_APPS.append("django_extensions")

# Django builtin setting
# Max size of a POST body (for event ingestion)
DATA_UPLOAD_MAX_MEMORY_SIZE = 20971520  # 20 MB

ROOT_URLCONF = "posthog.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["frontend/dist", "posthog/templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "loginas.context_processors.impersonated_session_status",
                "posthog.helpers.impersonation.impersonation_context",
            ]
        },
    }
]

WSGI_APPLICATION = "posthog.wsgi.application"

####
# Authentication

AUTHENTICATION_BACKENDS: list[str] = [
    "axes.backends.AxesStandaloneBackend",
    "social_core.backends.github.GithubOAuth2",
    "social_core.backends.gitlab.GitLabOAuth2",
    "django.contrib.auth.backends.ModelBackend",
    "posthog.auth.WebauthnBackend",
]

AUTH_USER_MODEL = "posthog.User"

LOGIN_URL = "/login"
LOGOUT_URL = "/logout"
LOGIN_REDIRECT_URL = "/"
APPEND_SLASH = False
CORS_URLS_REGEX = r"^(/site_app/|/array/|/static/|/oauth/token/?|/toolbar_oauth/check|/api/(?!early_access_features|surveys|web_experiments).*$)"
CORS_ALLOW_HEADERS = default_headers + CORS_ALLOWED_TRACING_HEADERS
X_FRAME_OPTIONS = "SAMEORIGIN"

SOCIAL_AUTH_JSONFIELD_ENABLED = True
SOCIAL_AUTH_USER_MODEL = "posthog.User"
SOCIAL_AUTH_REDIRECT_IS_HTTPS: bool = get_from_env("SOCIAL_AUTH_REDIRECT_IS_HTTPS", not DEBUG, type_cast=str_to_bool)

SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "ee.api.authentication.social_auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.social_auth.associate_by_email",
    "posthog.api.signup.social_create_user",
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
    "posthog.api.authentication.social_login_notification",
)

SOCIAL_AUTH_STRATEGY = "social_django.strategy.DjangoStrategy"
SOCIAL_AUTH_STORAGE = "social_django.models.DjangoStorage"
SOCIAL_AUTH_FIELDS_STORED_IN_SESSION = [
    "invite_id",
    "user_name",
    "email_opt_in",
    "organization_name",
    "reauth",
]
SOCIAL_AUTH_GITHUB_SCOPE = ["user:email"]
SOCIAL_AUTH_GITHUB_KEY: str | None = os.getenv("SOCIAL_AUTH_GITHUB_KEY")
SOCIAL_AUTH_GITHUB_SECRET: str | None = os.getenv("SOCIAL_AUTH_GITHUB_SECRET")

SOCIAL_AUTH_GITLAB_SCOPE = ["read_user"]
SOCIAL_AUTH_GITLAB_KEY: str | None = os.getenv("SOCIAL_AUTH_GITLAB_KEY")
SOCIAL_AUTH_GITLAB_SECRET: str | None = os.getenv("SOCIAL_AUTH_GITLAB_SECRET")
SOCIAL_AUTH_GITLAB_API_URL: str = os.getenv("SOCIAL_AUTH_GITLAB_API_URL", "https://gitlab.com")

LICENSE_SECRET_KEY = os.getenv("LICENSE_SECRET_KEY", "license-so-secret")

# Cookie age in seconds (default 2 weeks) - these are the standard defaults for Django but having it here to be explicit
SESSION_ENGINE = "posthog.session.backend"
SESSION_COOKIE_AGE = get_from_env("SESSION_COOKIE_AGE", 60 * 60 * 24 * 14, type_cast=int)

# For sensitive actions we have an additional permission (default 2 hour)
SESSION_SENSITIVE_ACTIONS_AGE = get_from_env("SESSION_SENSITIVE_ACTIONS_AGE", 60 * 60 * 2, type_cast=int)

SESSION_COOKIE_NAME = get_from_env("SESSION_COOKIE_NAME", "sessionid")
CSRF_COOKIE_NAME = "posthog_csrftoken"
CSRF_COOKIE_AGE = get_from_env("CSRF_COOKIE_AGE", SESSION_COOKIE_AGE, type_cast=int)

# The total time allowed for an impersonated session
IMPERSONATION_TIMEOUT_SECONDS = get_from_env("IMPERSONATION_TIMEOUT_SECONDS", 60 * 60 * 2, type_cast=int)
# The time allowed for an impersonated session to be idle before it expires
IMPERSONATION_IDLE_TIMEOUT_SECONDS = get_from_env("IMPERSONATION_IDLE_TIMEOUT_SECONDS", 30 * 60, type_cast=int)
# Impersonation cookie last activity key
IMPERSONATION_COOKIE_LAST_ACTIVITY_KEY = get_from_env(
    "IMPERSONATION_COOKIE_LAST_ACTIVITY_KEY", "impersonation_last_activity"
)
# Disallow impersonating other staff
CAN_LOGIN_AS = lambda request, target_user: (
    # user performing action must be a staff member
    request.user.is_staff
    # cannot impersonate other staff
    and not target_user.is_staff
    # target user must not have opted out of impersonation (None treated as allowed)
    and target_user.allow_impersonation is not False
)
# Require a reason when logging in as another user
LOGINAS_LOGIN_REASON_REQUIRED = True

SESSION_COOKIE_CREATED_AT_KEY = get_from_env("SESSION_COOKIE_CREATED_AT_KEY", "session_created_at")
# Master kill-switch for the session-risk middleware (posthog/session/middleware.py). On by default,
# off in the test suite (like AXES_ENABLED) so its per-request feature-flag check doesn't run during
# tests that assert posthoganalytics.feature_enabled call counts.
SESSION_RISK_ENABLED = get_from_env("SESSION_RISK_ENABLED", not TEST, type_cast=str_to_bool)
# Session keys for risk-based step-up (posthog/session/risk.py). Named so every reader/writer shares
# one source of truth, like SESSION_COOKIE_CREATED_AT_KEY above.
SESSION_STEP_UP_REQUIRED_KEY = get_from_env("SESSION_STEP_UP_REQUIRED_KEY", "step_up_required")
SESSION_LAST_REAUTH_AT_KEY = get_from_env("SESSION_LAST_REAUTH_AT_KEY", "last_reauth_at")

# Impossible-travel risk thresholds (see posthog/session/risk.py). Tunable without a code change.
RISK_DISTANCE_FLOOR_KM = get_from_env("RISK_DISTANCE_FLOOR_KM", 500.0, type_cast=float)
RISK_ELAPSED_FLOOR_S = get_from_env("RISK_ELAPSED_FLOOR_S", 300.0, type_cast=float)
RISK_VELOCITY_MAX_KMH = get_from_env("RISK_VELOCITY_MAX_KMH", 1000.0, type_cast=float)
# How often a low-risk request refreshes the known-good baseline snapshot (geo/UA + baseline_at).
# Throttles the per-request write; the baseline geo lags by at most this interval, fine for scoring.
RISK_BASELINE_REFRESH_S = get_from_env("RISK_BASELINE_REFRESH_S", 300.0, type_cast=float)

PROJECT_SWITCHING_TOKEN_ALLOWLIST = get_list(os.getenv("PROJECT_SWITCHING_TOKEN_ALLOWLIST", "sTMFPsFhdP1Ssg"))

####
# 2FA

TWO_FACTOR_REMEMBER_COOKIE_AGE = 60 * 60 * 24 * 30

####
# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "posthog.auth.ZxcvbnValidator"},
]

if TEST:
    # PBKDF2 is deliberately slow (~150ms per hash), which adds up because every
    # per-test user creation hashes a password. MD5 keeps the same hasher API with
    # none of the cost. Never used outside tests.
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

PASSWORD_RESET_TIMEOUT = 86_400  # 1 day

####
# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

####
# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATIC_URL = "/static/"
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "frontend/dist"),
]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if TEST
            else "whitenoise.storage.ManifestStaticFilesStorage"
        ),
    },
}


def static_varies_origin(headers, path, url):
    headers["Vary"] = "Accept-Encoding, Origin"


WHITENOISE_ADD_HEADERS_FUNCTION = static_varies_origin

# Per-IP signup throttle rate (see posthog.rate_limit.SignupIPThrottle). Overridable per-env so
# non-prod (e.g. dev deploy smoke-tests) can raise it without weakening the prod default.
SIGNUP_IP_THROTTLE_RATE = get_from_env("SIGNUP_IP_THROTTLE_RATE", "5/day")

# Email domains whose signups are created already-verified (skipping the email round-trip), so
# non-prod deploy smoke-tests can sign up and act immediately. Empty by default — prod verifies
# every signup.
EMAIL_VERIFICATION_SKIP_FOR_DOMAINS = [
    domain.lower() for domain in get_list(get_from_env("EMAIL_VERIFICATION_SKIP_FOR_DOMAINS", ""))
]

####
# REST framework

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["posthog.auth.SessionAuthentication"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["posthog.renderers.SafeJSONRenderer"],
    "PAGE_SIZE": 100,
    "EXCEPTION_HANDLER": "posthog.exceptions.exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "DEFAULT_SCHEMA_CLASS": "posthog.api.documentation.PostHogAutoSchema",
    # These rate limits are defined in `rate_limit.py`, and they're only
    # applied if env variable `RATE_LIMIT_ENABLED` is set to True
    "DEFAULT_THROTTLE_CLASSES": [
        "posthog.rate_limit.BurstRateThrottle",
        "posthog.rate_limit.SustainedRateThrottle",
    ],
    # The default STRICT_JSON fails the whole request if the data can't be strictly JSON-serialized
    "STRICT_JSON": False,
}

if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append("rest_framework.renderers.BrowsableAPIRenderer")  # type: ignore

####
# DRF Spectacular

SPECTACULAR_SETTINGS = {
    "OAS_VERSION": "3.1.0",
    "AUTHENTICATION_WHITELIST": ["posthog.auth.PersonalAPIKeyAuthentication"],
    "GET_MOCK_REQUEST": "posthog.api.documentation.build_openapi_mock_request",
    "PREPROCESSING_HOOKS": ["posthog.api.documentation.preprocess_exclude_path_format"],
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "products.dashboards.backend.widget_specs.pydantic_openapi.inject_widget_spec_pydantic_components",
        "posthog.api.documentation.custom_postprocessing_hook",
        # Runs last so it sees the final post-processed spec. Emits drf-spectacular warnings
        # for self-inconsistencies (default not in enum, required not in properties, $ref siblings)
        # so `--fail-on-warn` in `hogli build:openapi-schema` catches them in CI.
        "posthog.api.documentation.lint_spec_consistency_hook",
    ],
    "ENUM_NAME_OVERRIDES": {
        # If CI is failing with "enum naming encountered a non-optimally resolvable
        # collision" / "Format5eaEnum"-style warnings from `hogli build:openapi-schema`,
        # this is the dict you need to add an entry to. The warning fails CI because
        # `--fail-on-warn` is set on the `spectacular` invocation in hogli.yaml.
        #
        # Workflow to resolve a collision:
        #   1. Run `python manage.py find_enum_collisions` — it prints the field name,
        #      the auto-generated name (e.g. `Format5eaEnum`), the enum values, which
        #      components share the hash, and a suggested override entry. The suggestion
        #      is pastable as-is for inline-list collisions (type-hint enums and
        #      ChoiceFields with plain `choices=["A", "B"]`); only ChoiceFields with
        #      custom labels (TextChoices where labels differ from values) need the
        #      Choices/Enum class path filled in.
        #   2. Add the suggested entry below (pick the right category — see "hash trap"
        #      note below). Optionally rename the key from the auto-generated name to a
        #      more semantic one to improve the generated schema type's name.
        #   3. Re-run `hogli build:openapi-schema` locally to confirm the warning is gone.
        #
        # Full guide (when to use which pattern, anti-patterns, MCP/typegen implications):
        #   /improving-drf-endpoints  (skill — invoke it for the walkthrough)
        #
        # Hash trap — overrides fall into two categories depending on how drf-spectacular
        # hashes them, and using the wrong format silently fails (the override is ignored
        # and the warning persists):
        #
        # 1. Model class paths — used for ChoiceField-backed enums whose labels differ
        #    from their values (typical `TextChoices` with explicit labels). The override
        #    must point to the same Choices/Enum class so _load_enum_name_overrides hashes
        #    identically to the x-spec-enum-id.
        #
        # 2. Inline value lists — used for Enum type-hint enums (SerializerMethodField
        #    return types) AND ChoiceFields whose choices are plain lists (labels equal
        #    values). The override must be a plain value list, which
        #    _load_enum_name_overrides normalizes to (value, value) tuples — matching
        #    both the no-x-spec-enum-id type-hint path and the inline-choices ChoiceField
        #    path (drf-spectacular generates the x-spec-enum-id from the same tuples).
        # --- Model class paths (ChoiceField x-spec-enum-id hashes) ---
        "EngineeringAnalyticsPRStateEnum": "products.engineering_analytics.backend.facade.contracts.PRState",
        "QuarantineModeEnum": "products.engineering_analytics.backend.facade.contracts.QuarantineMode",
        "RestrictionLevelEnum": "products.dashboards.backend.models.dashboard.Dashboard.RestrictionLevel",
        "OrganizationMembershipLevelEnum": "posthog.models.organization.OrganizationMembership.Level",
        "SetupTaskId": "posthog.models.team.setup_tasks.SetupTaskId",
        "SurveyType": "products.surveys.backend.models.Survey.SurveyType",
        "ConversationStatus": "products.posthog_ai.backend.models.assistant.Conversation.Status",
        "ConversationType": "products.posthog_ai.backend.models.assistant.Conversation.Type",
        "DetailModeEnum": "products.ai_observability.backend.summarization.models.SummarizationMode",
        "SavedQueryStatusEnum": "products.data_modeling.backend.models.datawarehouse_saved_query.DataWarehouseSavedQuery.Status",
        "PushTokenPlatformEnum": "posthog.models.user_push_token.UserPushToken.Platform",
        "PropertyDefinitionTypeEnum": "products.event_definitions.backend.models.property_definition.PropertyType",
        "ExternalDataSourceTypeEnum": "products.warehouse_sources.backend.types.ExternalDataSourceType",
        "ExperimentMetricKindEnum": "products.ai_observability.backend.models.score_definitions.ScoreDefinition.Kind",
        "EvaluationTargetEnum": "products.ai_observability.backend.models.evaluations.EvaluationTarget",
        "IntegrationKindEnum": "posthog.models.integration.Integration.IntegrationKind",
        "TicketStatusEnum": "products.conversations.backend.models.constants.Status",
        "HealthIssueStatusEnum": "posthog.models.health_issue.HealthIssue.Status",
        "HealthIssueSeverityEnum": "posthog.models.health_issue.HealthIssue.Severity",
        "IngestionWarningSeverityEnum": "posthog.api.ingestion_warnings_v2.INGESTION_WARNING_SEVERITIES",
        # Disambiguates from the same-valued inline enum on the signals LogsAlertStateChangeSignalExtra contract.
        "LogsAlertThresholdOperatorEnum": "products.logs.backend.models.LogsAlertConfiguration.ThresholdOperator",
        "LLMProviderEnum": "products.ai_observability.backend.models.provider_keys.LLMProvider",
        "EvaluationReportFrequencyEnum": (
            "products.ai_observability.backend.models.evaluation_reports.EvaluationReport.Frequency"
        ),
        "HogFlowStatusEnum": "products.workflows.backend.models.hog_flow.hog_flow.HogFlow.State",
        "MCPAuthTypeEnum": "products.mcp_store.backend.models.AUTH_TYPE_CHOICES",
        "TaskRunStatusEnum": "products.tasks.backend.models.TaskRun.Status",
        "TaskRunEnvironmentEnum": "products.tasks.backend.models.TaskRun.Environment",
        "ModelEnum": "products.batch_exports.backend.models.batch_export.BatchExport.Model",
        "RecurrenceIntervalEnum": "products.reminders.backend.models.reminder.Reminder.RecurrenceInterval",
        "ScannerModelEnum": "products.replay_vision.backend.models.replay_scanner.ScannerModel",
        "ScannerTypeEnum": "products.replay_vision.backend.models.replay_scanner.ScannerType",
        "ScannerProviderEnum": "products.replay_vision.backend.models.replay_scanner.ScannerProvider",
        "ObservationStatusEnum": "products.replay_vision.backend.models.replay_observation.ObservationStatus",
        "ObservationTriggerEnum": "products.replay_vision.backend.models.replay_observation.ObservationTrigger",
        "ExportedRecordingStatusEnum": "products.replay.backend.models.exported_recording.ExportedRecording.Status",
        "VisionActionRunStatusEnum": "products.replay_vision.backend.models.vision_action.VisionActionRunStatus",
        "AutonomyPriorityEnum": "products.signals.backend.models.AutonomyPriority",
        "UserInterviewSearchDocumentTypeEnum": "products.user_interviews.backend.facade.enums.SEARCH_DOCUMENT_TYPES",
        "BatchExportRunStatusEnum": "products.batch_exports.backend.models.batch_export.BatchExportRun.Status",
        "HeatmapType": "products.web_analytics.backend.models.heatmap_saved.SavedHeatmap.Type",
        # --- Inline value lists (type-hint enums, no x-spec-enum-id) ---
        "PropertyGroupOperator": ["AND", "OR"],
        # bulk_update_tags exposes an identical add/remove/set `action` ChoiceField on both
        # BulkUpdateTagsRequest and its UUID subclass, so the shared enum can't be component-prefixed
        # unambiguously and auto-resolves to a hash name. Pin it to a stable name.
        "BulkUpdateTagsActionEnum": ["add", "remove", "set"],
        # Full signal taxonomy on the report `signals` endpoint; the source-config serializer's
        # subset enums keep their own auto-resolved names.
        "SignalSourceProduct": "products.signals.backend.enums.SIGNAL_SOURCE_PRODUCT_VALUES",
        "SignalSourceType": "products.signals.backend.enums.SIGNAL_SOURCE_TYPE_VALUES",
        # AgentRevision.state (model ChoiceField) and RevisionNotDraftError.state (the
        # bundle-edit 409 body) share one choice set — pin them to a single named enum.
        "AgentRevisionStateEnum": ["draft", "ready", "live", "archived"],
        "CustomPropertyDisplayTypeEnum": [
            "text",
            "number",
            "currency",
            "percent",
            "date",
            "datetime",
            "boolean",
            "select",
        ],
        # Pinned pre-emptively: the auto-name would be the collision-prone "ColorEnum", and adding a
        # palette color later would change the hash and silently rename the generated type.
        "CustomPropertyOptionColorEnum": [f"preset-{i}" for i in range(1, 11)],
        # Experiment now has two serializers (full ExperimentSerializer + ExperimentBasicSerializer
        # for the list endpoint) that both expose `type`/`status`. Pin both to their pre-existing
        # generated names so the shared enums don't get component-prefixed auto-names on collision.
        "ExperimentTypeEnum": ["web", "product", None],
        "ExperimentStatusEnum": ["draft", "running", "paused", "exposure_frozen", "stopped"],
        # Two `sync_frequency` ChoiceFields with different member sets: warehouse-source schemas
        # accept sub-15min cadences, while saved-query (view) materialization floors at 15min.
        # Pin both to stable names so neither gets a component-prefixed auto-name on collision.
        # "SyncFrequencyEnum" keeps the source-schema enum at its pre-existing generated name.
        "SyncFrequencyEnum": [
            "never",
            "1min",
            "5min",
            "15min",
            "30min",
            "1hour",
            "6hour",
            "12hour",
            "24hour",
            "7day",
            "30day",
        ],
        "SavedQuerySyncFrequencyEnum": [
            "never",
            "15min",
            "30min",
            "1hour",
            "6hour",
            "12hour",
            "24hour",
            "7day",
            "30day",
        ],
        # Signals now has two serializers (single SignalReportStateRequest + bulk
        # SignalReportBulkStateRequest) that both expose the same `state` ChoiceField. Pin the
        # shared enum to a stable name so it doesn't collide with the other `state` enums
        # (tasks, cdp) into a component-prefixed auto-name.
        "SignalReportStateEnum": ["suppressed", "potential"],
        # Two serializers now expose an `op` ChoiceField (metrics filters and email-template design
        # patches). Pin both to stable names so neither gets a component-prefixed auto-name on collision.
        # "OpEnum" keeps the metrics filter enum at its pre-existing generated name.
        "OpEnum": ["eq", "neq", "regex", "not_regex"],
        "EmailTemplateDesignOperationEnum": [
            "update_content",
            "update_column",
            "update_row",
            "update_body",
            "add_content",
            "remove_content",
            "move_content",
            "add_row",
            "remove_row",
        ],
        "PropertyFilterTypeEnum": [
            "event",
            "event_metadata",
            "feature",
            "person",
            "person_metadata",
            "cohort",
            "element",
            "static-cohort",
            "dynamic-cohort",
            "precalculated-cohort",
            "group",
            "recording",
            "log_entry",
            "behavioral",
            "session",
            "hogql",
            "data_warehouse",
            "data_warehouse_person_property",
            "error_tracking_issue",
            "log",
            "log_attribute",
            "log_resource_attribute",
            "span",
            "span_attribute",
            "span_resource_attribute",
            "revenue_analytics",
            "flag",
            "workflow_variable",
        ],
        "AssigneeTypeEnum": ["user", "role"],
        "AgentSessionStateEnum": ["queued", "running", "completed", "closed", "cancelled", "failed"],
        "ScoutOriginEnum": ["canonical", "custom"],
        "FileFormatEnum": ["Parquet", "JSONLines"],
        "MetricAttributeScopeEnum": ["resource", "attribute", "auto"],
        "MetricQueryIntervalEnum": ["second", "minute", "minute_5", "minute_15", "hour", "hour_6", "day", "week"],
        "MetricAnomalyDirectionEnum": ["up", "down", "flat"],
        "WoWChangeDirectionEnum": ["Up", "Down"],
        "BatchExportIntervalEnum": ["hour", "day", "week", "every 5 minutes", "every 15 minutes"],
        "ErrorTrackingIssueOrderByEnum": ["last_seen", "first_seen", "occurrences", "users", "sessions"],
        "ErrorTrackingIssueStatusEnum": ["archived", "active", "resolved", "pending_release", "suppressed", "all"],
        # Dashboard widget polymorphic OpenAPI: each per-type serializer uses a singleton
        # widget_type ChoiceField (one value). drf-spectacular hashes enum value sets — without
        # a per-type override they all collide into one mangled name. Override key is the
        # stable component name; value is the singleton list even though length is 1.
        "ActivityEventsListWidgetTypeEnum": ["activity_events_list"],
        "ErrorTrackingListWidgetTypeEnum": ["error_tracking_list"],
        "SessionReplayListWidgetTypeEnum": ["session_replay_list"],
        "ExperimentsListWidgetTypeEnum": ["experiments_list"],
        "ExperimentResultsWidgetTypeEnum": ["experiment_results"],
        "SurveyResultsWidgetTypeEnum": ["survey_results"],
        "LogsListWidgetTypeEnum": ["logs_list"],
        "OrderByEnum": ["latest", "earliest"],
        "PropertyGroupTypeEnum": ["cohort", "person", "group"],
        "ExistenceOperatorEnum": ["is_set", "is_not_set"],
        "TaskExecutionModeEnum": ["interactive", "background"],
        # Shared by ClaudeTaskRunCreateSchema and SandboxOpen (the conversations `open` body).
        "InitialPermissionModeEnum": ["default", "acceptEdits", "plan", "bypassPermissions", "auto"],
        "HogFunctionTemplatingEnum": ["hog", "liquid"],
        "HogFlowEdgeTypeEnum": ["continue", "branch"],
        "SourceMatchEnum": ["none", "auto", "mapped"],
        "NotificationDestinationTypeEnum": ["slack", "webhook", "teams"],
        "TaskRunArtifactTypeEnum": [
            "plan",
            "context",
            "reference",
            "output",
            "artifact",
            "tree_snapshot",
            "user_attachment",
            "skill_bundle",
        ],
        # Same-value collisions: identical choice sets appear on fields with different names.
        # href_matching, text_matching, url_matching on ActionStep all share the same choices.
        "ActionStepMatchingEnum": ["contains", "regex", "exact"],
        # effective_restriction_level and effective_privilege_level are SerializerMethodFields
        # returning Dashboard.RestrictionLevel/PrivilegeLevel (IntegerChoices).  Since they
        # go through the type-hint path (no x-spec-enum-id), they hash as (value, value).
        "EffectivePrivilegeLevelEnum": [(21, 21), (37, 37)],
        # effective_membership_level and level on OrganizationMember use the same int values.
        "EffectiveMembershipLevelEnum": [(1, 1), (8, 8), (15, 15)],
        # descriptionContentType and thankYouMessageDescriptionContentType share values.
        "DescriptionContentTypeEnum": ["text", "html"],
        # Field-name collisions: multiple different choice sets use the same field name
        # across different serializer components.
        "StringMatchOperatorEnum": ["exact", "is_not", "icontains", "not_icontains", "regex", "not_regex"],
        "DateOperatorEnum": ["is_date_exact", "is_date_before", "is_date_after"],
        "DetailModeValueEnum": ["minimal", "detailed"],
        "LogsAlertConfigurationStateEnum": "products.logs.backend.models.LogsAlertConfiguration.State",
        # runtime_adapter on TaskRunCreateRequestSerializer (full set) vs
        # ClaudeTaskRunCreateSchemaSerializer and CodexTaskRunCreateSchemaSerializer (subsets).
        "RuntimeAdapterEnum": ["claude", "codex"],
        "ClaudeRuntimeAdapterEnum": ["claude"],
        "CodexRuntimeAdapterEnum": ["codex"],
        # StaffCacheEntryResponse.source and StaffCacheEntryStatus.source share the same
        # redis/miss choice set. Pin to a stable name so the collision doesn't auto-resolve
        # to a hash name.
        "StaffCacheSourceEnum": ["redis", "miss"],
    },
}

EXCEPTIONS_HOG = {"EXCEPTION_REPORTING": "posthog.exceptions.exception_reporting"}

####
# Compression

# see posthog.gzip_middleware.ScopedGZipMiddleware
# for how adding paths here can add vulnerability to the "breach" attack
GZIP_POST_RESPONSE_ALLOW_LIST = get_list(
    os.getenv(
        "GZIP_POST_RESPONSE_ALLOW_LIST",
        ",".join(
            [
                "^/?api/(environments|projects)/\\d+/query/?$",
            ]
        ),
    )
)

GZIP_RESPONSE_ALLOW_LIST = get_list(
    os.getenv(
        "GZIP_RESPONSE_ALLOW_LIST",
        ",".join(
            [
                "^/?external_surveys/[^/]+/?$",
                "^/?api/plugin_config/\\d+/frontend/?$",
                "^/?api/(environments|projects)/@current/property_definitions/?$",
                "^/?api/(environments|projects)/\\d+/event_definitions/?$",
                "^/?api/(environments|projects)/\\d+/insights/(trend|funnel)/?$",
                "^/?api/(environments|projects)/\\d+/insights/?$",
                "^/?api/(environments|projects)/\\d+/insights/\\d+/?$",
                "^/?api/(environments|projects)/\\d+/dashboards/\\d+/?$",
                "^/?api/(environments|projects)/\\d+/dashboards/?$",
                "^/?api/(environments|projects)/\\d+/actions/?$",
                "^/?api/(environments|projects)/\\d+/session_recordings/?$",
                "^/?api/(environments|projects)/\\d+/session_recordings/.*$",
                "^/?api/(environments|projects)/\\d+/session_recording_playlists/?$",
                "^/?api/(environments|projects)/\\d+/session_recording_playlists/.*$",
                "^/?api/(environments|projects)/\\d+/performance_events/?$",
                "^/?api/(environments|projects)/\\d+/performance_events/.*$",
                "^/?api/(environments|projects)/\\d+/exports/\\d+/content/?$",
                "^/?api/(environments|projects)/\\d+/my_notifications/?$",
                "^/?api/(environments|projects)/\\d+/uploaded_media/?$",
                "^/uploaded_media/.*$",
                "^/api/element/stats/?$",
                "^/api/(environments|projects)/\\d+/cohorts/?$",
                "^/api/(environments|projects)/\\d+/persons/?$",
                "^/api/organizations/@current/plugins/?$",
                "^api/(environments|projects)/@current/feature_flags/my_flags/?$",
                "^/?api/(environments|projects)/\\d+/query/?$",
                "^/?api/instance_status/?$",
                "^/array/.*$",
            ]
        ),
    )
)

####
# Prometheus Django metrics settings, see
# https://github.com/korfuri/django-prometheus for more details

# We keep the number of buckets low to reduce resource usage on the Prometheus
PROMETHEUS_LATENCY_BUCKETS = [0.1, 0.3, 0.9, 2.7, 8.1, float("inf")]

####
# Proxy and IP egress config

# Used only to display in the UI to inform users of allowlist options
PUBLIC_EGRESS_IP_ADDRESSES = get_list(os.getenv("PUBLIC_EGRESS_IP_ADDRESSES", ""))

PROXY_PROVISIONER_URL = get_from_env("PROXY_PROVISIONER_URL", "")  # legacy, from before gRPC
PROXY_PROVISIONER_ADDR = get_from_env("PROXY_PROVISIONER_ADDR", "")
PROXY_USE_GATEWAY_API = get_from_env("PROXY_USE_GATEWAY_API", False, type_cast=str_to_bool)
PROXY_TARGET_CNAME = get_from_env("PROXY_TARGET_CNAME", "")
PROXY_BASE_CNAME = get_from_env("PROXY_BASE_CNAME", "")

# Cloudflare for SaaS proxy settings
CLOUDFLARE_PROXY_ENABLED = get_from_env("CLOUDFLARE_PROXY_ENABLED", False, type_cast=str_to_bool)
CLOUDFLARE_API_TOKEN = get_from_env("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ZONE_ID = get_from_env("CLOUDFLARE_ZONE_ID", "")
CLOUDFLARE_WORKER_NAME = get_from_env("CLOUDFLARE_WORKER_NAME", "")
CLOUDFLARE_PROXY_BASE_CNAME = get_from_env("CLOUDFLARE_PROXY_BASE_CNAME", "")

# Domain Connect (automated DNS configuration)
DOMAIN_CONNECT_PRIVATE_KEY: str | None = os.getenv("DOMAIN_CONNECT_PRIVATE_KEY", "").replace("\\n", "\n") or None
DOMAIN_CONNECT_KEY_ID: str = os.getenv("DOMAIN_CONNECT_KEY_ID", "_dcpubkeyv1")

####
# CDP

LOGO_DEV_TOKEN = get_from_env("LOGO_DEV_TOKEN", "")

####
# Feature flag billing analytics
# Used to track feature flag requests for billing purposes.
# Named "decide" for historical reasons: the /decide endpoint was the original
# way clients fetched feature flags before the Rust feature flags service.
DECIDE_BILLING_SAMPLING_RATE = get_from_env("DECIDE_BILLING_SAMPLING_RATE", 0.1, type_cast=float)
DECIDE_BILLING_ANALYTICS_TOKEN = get_from_env("DECIDE_BILLING_ANALYTICS_TOKEN", None, type_cast=str, optional=True)

####
# /remote_config
REMOTE_CONFIG_DECIDE_ROLLOUT_PERCENTAGE = get_from_env("REMOTE_CONFIG_DECIDE_ROLLOUT_PERCENTAGE", 0.0, type_cast=float)

if REMOTE_CONFIG_DECIDE_ROLLOUT_PERCENTAGE > 1:
    raise ValueError(
        f"REMOTE_CONFIG_DECIDE_ROLLOUT_PERCENTAGE must be between 0 and 1 but got {REMOTE_CONFIG_DECIDE_ROLLOUT_PERCENTAGE}"
    )
REMOTE_CONFIG_CDN_PURGE_ENDPOINT = get_from_env("REMOTE_CONFIG_CDN_PURGE_ENDPOINT", "")
REMOTE_CONFIG_CDN_PURGE_TOKEN = get_from_env("REMOTE_CONFIG_CDN_PURGE_TOKEN", "")
REMOTE_CONFIG_CDN_PURGE_DOMAINS = get_list(os.getenv("REMOTE_CONFIG_CDN_PURGE_DOMAINS", ""))

# Versioned posthog-js S3 bucket — enables versioned JS content serving when set
POSTHOG_JS_S3_BUCKET = get_from_env("POSTHOG_JS_S3_BUCKET", "")
# CDN cache control for array.js responses
POSTHOG_JS_CDN_MAX_AGE = int(os.getenv("POSTHOG_JS_CDN_MAX_AGE", "3600"))
POSTHOG_JS_CDN_STALE_WHILE_REVALIDATE = int(os.getenv("POSTHOG_JS_CDN_STALE_WHILE_REVALIDATE", "86400"))
POSTHOG_JS_CDN_STALE_IF_ERROR = int(os.getenv("POSTHOG_JS_CDN_STALE_IF_ERROR", "86400"))

####
# /capture

KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS = int(os.getenv("KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS", None) or 10)

####
# /query

# if `true` we highly increase the rate limit on /query endpoint and limit the number of concurrent queries
API_QUERIES_ENABLED = get_from_env("API_QUERIES_ENABLED", False, type_cast=str_to_bool)

####
# /api/environments deprecation

# Requests to /api/environments/* are served through the equivalent /api/projects/*
# viewset via an in-process path rewrite, gated by the `api-environments-redirect`
# feature flag — see posthog.middleware.EnvironmentsRewriteMiddleware.
# ISO date announced to integrators via the `Sunset` response header (RFC 8594) on
# /api/environments/* responses. Empty string omits the header.
API_ENVIRONMENTS_SUNSET_DATE = get_from_env("API_ENVIRONMENTS_SUNSET_DATE", "2026-07-31")

# Query service SLO sampling rate. Each QueryRunner.run() call emits two events
# (slo_operation_started + slo_operation_completed); unsampled, that's many millions of
# events per day. The chosen rate is stamped on each event as `properties.sample_rate`
# so dashboards can weight by 1/sample_rate to reconstruct true counts. Tunable via env
# var without redeploy. 1.0 = emit every operation, 0.01 = 1% sample.
# Defaults to 1.0 under TEST so assertions on emitted SLO events are deterministic.
QUERY_SERVICE_SLO_SAMPLE_RATE = get_from_env("QUERY_SERVICE_SLO_SAMPLE_RATE", 1.0 if TEST else 0.01, type_cast=float)

####
# Livestream

# Passed to the frontend for the web app to know where to connect to
LIVESTREAM_HOST = get_from_env("LIVESTREAM_HOST", "")

####
# Graceful shutdown

# Marker file created by Kubernetes preStop hook to signal pod is shutting down.
# When this file exists, the /_readyz endpoint returns 503 to stop receiving new traffic.
PRESTOP_MARKER_FILE = get_from_env("PRESTOP_MARKER_FILE", "/tmp/posthog_prestop")

####
# Local dev

# disables frontend side navigation hooks to make hot-reload work seamlessly
DEV_DISABLE_NAVIGATION_HOOKS = get_from_env("DEV_DISABLE_NAVIGATION_HOOKS", False, type_cast=bool)

# one-click passwordless login on the login page (also requires DEBUG)
ALLOW_DEV_LOGIN = get_from_env("ALLOW_DEV_LOGIN", False, type_cast=str_to_bool)

####
# Random/temporary
# Everything that is supposed to be removed eventually

# temporary flag to control new UUID version setting in posthog-js
# is set to v7 to test new generation but can be set to "og" to revert
POSTHOG_JS_UUID_VERSION = os.getenv("POSTHOG_JS_UUID_VERSION", "v7")

# Feature flag to enable HogFunctions daily digest email for specific teams
# Comma-separated list of team IDs that should receive the digest
HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS = get_list(get_from_env("HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS", ""))

# Maximum audience size for HogFlow batch triggers. Default that applies to all teams unless they
# opt in to the elevated value below. Only used to inform the frontend UI; no backend enforcement.
HOGFLOW_BATCH_TRIGGER_LIMIT = int(get_from_env("HOGFLOW_BATCH_TRIGGER_LIMIT", 50000))
# Elevated maximum audience size, returned for teams listed in HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS.
HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED = int(get_from_env("HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED", 100000))
# Comma-separated list of team IDs that get the elevated batch trigger limit instead of the default.
# Empty by default — everyone gets the 50k tier. Opt-in via env override for teams needing 100k.
HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS: set[int] = {
    int(team_id) for team_id in get_list(get_from_env("HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS", ""))
}

# Comma-separated list of org ids allowed to receive the Error Tracking weekly digest
# "*" for all, empty to disable feature
ERROR_TRACKING_WEEKLY_DIGEST_ORG_IDS = get_list(get_from_env("ERROR_TRACKING_WEEKLY_DIGEST_ORG_IDS", ""))

# Comma-separated list of email addresses allowed to receive the Error Tracking weekly digest
# "*" for all
ERROR_TRACKING_WEEKLY_DIGEST_ALLOWED_EMAILS = get_list(get_from_env("ERROR_TRACKING_WEEKLY_DIGEST_ALLOWED_EMAILS", ""))

# webhook secret used initially for ET weekly digest workflow webhook but feel free to adopt it
WORKFLOWS_WEBHOOK_SECRET = get_from_env("WORKFLOWS_WEBHOOK_SECRET", "")

####
# OAuth

OIDC_RSA_PRIVATE_KEY = os.getenv("OIDC_RSA_PRIVATE_KEY", "").replace("\\n", "\n")

# Saving an RS256 OAuthApplication validates that this key is set, so a test run without one
# (fork PRs, bare local environments) fails in every test that creates an OAuth app. Generate
# an ephemeral key so tests never depend on an env-provided key.
if TEST and not OIDC_RSA_PRIVATE_KEY:
    OIDC_RSA_PRIVATE_KEY = generate_rsa_private_key_pem()

OIDC_RSA_PRIVATE_KEY_INACTIVE_1 = os.getenv("OIDC_RSA_PRIVATE_KEY_INACTIVE_1", "").replace("\\n", "\n")
OIDC_RSA_PRIVATE_KEY_INACTIVE_2 = os.getenv("OIDC_RSA_PRIVATE_KEY_INACTIVE_2", "").replace("\\n", "\n")
OIDC_RSA_PRIVATE_KEYS_INACTIVE = [
    key for key in (OIDC_RSA_PRIVATE_KEY_INACTIVE_1, OIDC_RSA_PRIVATE_KEY_INACTIVE_2) if key
]

OAUTH_EXPIRED_TOKEN_RETENTION_PERIOD = 60 * 60 * 24 * 30  # 30 days

OAUTH2_PROVIDER = {
    "OIDC_ENABLED": True,
    "PKCE_REQUIRED": True,  # We require PKCE for all OAuth flows - including confidential clients
    "OIDC_RSA_PRIVATE_KEY": OIDC_RSA_PRIVATE_KEY,
    "OIDC_RSA_PRIVATE_KEYS_INACTIVE": OIDC_RSA_PRIVATE_KEYS_INACTIVE,
    "SCOPES": {
        "openid": "OpenID Connect scope",
        "profile": "Access to user's profile",
        "email": "Access to user's email address",
        "introspection": "Access to introspect tokens",
        "*": "Full access to all scopes",
        # Strict-excludes INTERNAL_API_SCOPE_OBJECTS (e.g. `signal_scout_internal`) so they
        # can never be granted via the OAuth consent flow. The Signals scout harness token
        # is minted by direct DB insert (posthog/temporal/oauth.py) and never hits /authorize,
        # so it does not need to appear here.
        **get_scope_descriptions(),
    },
    # Block dangerous URI schemes that could be used for attacks
    # Since we use DCR with pre-registration, clients can use any scheme not in this blocklist
    # Security validation in OAuthApplication.clean() ensures http is only allowed for loopback addresses
    "BLOCKED_REDIRECT_URI_SCHEMES": [
        "javascript",  # XSS attacks
        "data",  # Data exfiltration / XSS
        "file",  # Local file access
        "blob",  # Similar to data URIs
        "vbscript",  # Legacy script injection
    ],
    "AUTHORIZATION_CODE_EXPIRE_SECONDS": 60 * 5,
    # client has 5 minutes to complete the OAuth flow before the authorization code expires
    "DEFAULT_SCOPES": ["openid"],
    "ACCESS_TOKEN_GENERATOR": "posthog.models.utils.generate_random_oauth_access_token",
    "REFRESH_TOKEN_GENERATOR": "posthog.models.utils.generate_random_oauth_refresh_token",
    "OAUTH2_VALIDATOR_CLASS": "posthog.api.oauth.views.OAuthValidator",
    "ACCESS_TOKEN_EXPIRE_SECONDS": 60 * 60,  # 1 hour
    "ROTATE_REFRESH_TOKEN": True,  # Rotate the refresh token whenever a new access token is issued
    "REFRESH_TOKEN_REUSE_PROTECTION": True,
    # The default grace period where a client can attempt to use the same refresh token
    # Using a refresh token after this will revoke all refresh and access tokens
    "REFRESH_TOKEN_GRACE_PERIOD_SECONDS": 60 * 2,
    "REFRESH_TOKEN_EXPIRE_SECONDS": 60 * 60 * 24 * 30,
    "CLEAR_EXPIRED_TOKENS_BATCH_SIZE": 1000,
    "CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL": 1,
}

OAUTH2_PROVIDER_APPLICATION_MODEL = "posthog.OAuthApplication"
OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL = "posthog.OAuthAccessToken"
OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL = "posthog.OAuthRefreshToken"
OAUTH2_PROVIDER_ID_TOKEN_MODEL = "posthog.OAuthIDToken"
OAUTH2_PROVIDER_GRANT_MODEL = "posthog.OAuthGrant"

ID_JAG_ACCESS_TOKEN_TTL_SECONDS: int = get_from_env("ID_JAG_ACCESS_TOKEN_TTL_SECONDS", 60 * 60 * 2, type_cast=int)
ID_JAG_CLOCK_SKEW_SECONDS: int = get_from_env("ID_JAG_CLOCK_SKEW_SECONDS", 30, type_cast=int)
ID_JAG_JWKS_CACHE_TTL_SECONDS: int = get_from_env("ID_JAG_JWKS_CACHE_TTL_SECONDS", 60 * 60, type_cast=int)

# Extra accepted ID-JAG `aud` values (the advertised authorization-server issuer) beyond SITE_URL —
# e.g. the OAuth proxy "https://oauth.posthog.com" on Cloud. SITE_URL is always accepted.
ID_JAG_ALLOWED_AUDIENCES: list[str] = get_list(get_from_env("ID_JAG_ALLOWED_AUDIENCES", ""))
# Extra accepted ID-JAG `resource` values (the advertised resource-server identifier) beyond SITE_URL —
# e.g. "https://mcp.posthog.com,https://mcp.us.posthog.com" on Cloud. SITE_URL is always accepted.
ID_JAG_ALLOWED_RESOURCES: list[str] = get_list(get_from_env("ID_JAG_ALLOWED_RESOURCES", ""))

TOOLBAR_OAUTH_STATE_TTL_SECONDS = 60 * 5
TOOLBAR_OAUTH_EXCHANGE_TIMEOUT_SECONDS = 10
TOOLBAR_OAUTH_APPLICATION_NAME = "PostHog Toolbar"
TOOLBAR_OAUTH_SCOPES = [
    "openid",
    "user:read",
    "action:read",
    "action:write",
    "feature_flag:read",
    "experiment:read",
    "experiment:write",
    "query:read",
    "product_tour:read",
    "product_tour:write",
    "heatmap:read",
    "element:read",
    "uploaded_media:write",
    "survey:read",
    "survey:write",
    "field_note:read",
    "field_note:write",
]

ELEMENT_STATS_DEFAULT_LIMIT = get_from_env("ELEMENT_STATS_DEFAULT_LIMIT", 50_000, type_cast=int)

# AI gateway internal admin API (wallet read + credit top-up from Django admin).
# Server-side shared secret; never expose the token to the browser.
AI_GATEWAY_INTERNAL_URL = get_from_env("AI_GATEWAY_INTERNAL_URL", "")
AI_GATEWAY_INTERNAL_TOKEN = get_from_env("AI_GATEWAY_INTERNAL_TOKEN", "")

# AI gateway inference endpoint: OpenAI-compatible URL (include /v1) + phs_ project
# secret for routing LLM calls through the gateway. Unset = direct to the provider.
AI_GATEWAY_URL = get_from_env("AI_GATEWAY_URL", "")
AI_GATEWAY_API_KEY = get_from_env("AI_GATEWAY_API_KEY", "")

# Sharing configuration settings
SHARING_TOKEN_GRACE_PERIOD_SECONDS = 60 * 5  # 5 minutes

# Teams force-enrolled in web analytics lazy precompute: the eligibility gate
# bypasses the org rollout flag for these, and the eager warmer uses the same
# list as its audience — one source of truth so warmer and reader cannot drift.
# The default enrolls the Cloud dogfooding team (project 2) ONLY on Cloud —
# never self-hosted, where lazy precompute is Cloud-only and project id 2 is an
# arbitrary customer project. A comma-separated env var overrides it on any
# deployment; changing enrollment is a deploy-time env-var change (Django +
# Dagster), not runtime-overridable.
_LAZY_PRECOMPUTE_DEFAULT_TEAM_IDS = (
    "2" if (CLOUD_DEPLOYMENT or "").upper() in ("EU", "US", "DEV", "E2E") and not TEST else ""
)
WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS: list[int] = [
    int(team_id)
    for team_id in get_list(get_from_env("WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS", _LAZY_PRECOMPUTE_DEFAULT_TEAM_IDS))
]

# Teams allowed to precompute *any* web analytics query, not just the
# single-`$host`-exact filter shape the general gate permits. For these teams the
# eligibility gate skips the filter-shape restriction (arbitrary property filters
# become distinct cache keys via `property_to_expr`) and flips the per-query
# toggle from opt-in to opt-out (precompute runs unless the user explicitly turns
# it off). Membership here also implies precompute enrollment, so a team need not
# also appear in `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS`. Same Cloud-only
# default (project 2) and comma-separated env-var override as the enrollment list.
WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS: list[int] = [
    int(team_id)
    for team_id in get_list(
        get_from_env("WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS", _LAZY_PRECOMPUTE_DEFAULT_TEAM_IDS)
    )
]

# Teams whose PATHS precompute reads also dual-write into the colocated
# `web_stats_paths_preaggregated_pathkey` table so its read layout can be
# A/B-compared (PR #64948). Deliberately narrow — only the named teams pay the
# extra mirror write — and defaults to the Cloud dogfooding team (project 2)
# only, same as the precompute lists above. Temporary; removed once the
# comparison concludes.
WEB_STATS_PATHS_PREAGG_MIRROR_PATHKEY_TEAM_IDS: list[int] = [
    int(team_id)
    for team_id in get_list(
        get_from_env("WEB_STATS_PATHS_PREAGG_MIRROR_PATHKEY_TEAM_IDS", _LAZY_PRECOMPUTE_DEFAULT_TEAM_IDS)
    )
]
