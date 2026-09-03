# Web app specific settings/middleware/apps setup
import os
import json
from datetime import timedelta

import structlog
from corsheaders.defaults import default_headers
from whitenoise.compress import Compressor

from posthog.openapi.enum_names import ChoicesEnumNameOverrides
from posthog.scopes import get_scope_descriptions
from posthog.settings.base_variables import BASE_DIR, CLOUD_DEPLOYMENT, DEBUG, TEST
from posthog.settings.utils import generate_rsa_private_key_pem, get_from_env, get_list, str_to_bool
from posthog.utils_cors import CORS_ALLOWED_TRACING_HEADERS

logger = structlog.get_logger(__name__)

####
# Deprecated insight `dashboards` field: session-authenticated callers always need to opt in with
# `include_dashboards`. While False, API-token callers still receive the field; flipping to True
# enforces the opt-in for them too. Env-toggleable so token enforcement can be reverted without a
# code change.
INSIGHT_DASHBOARDS_OPT_IN_ENFORCED = get_from_env("INSIGHT_DASHBOARDS_OPT_IN_ENFORCED", False, type_cast=str_to_bool)

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
    "products.canvas.backend.apps.CanvasConfig",
    "products.stamphog.backend.apps.StamphogConfig",
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
    "products.managed_warehouse.backend.apps.ManagedWarehouseConfig",
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
    "products.review_hog.backend.apps.ReviewHogConfig",
    "products.logs.backend.apps.LogsConfig",
    "products.billing_alerts.backend.apps.BillingAlertsConfig",
    "products.context_layer.backend.apps.ContextLayerAppConfig",
    "products.tracing.backend.apps.TracingConfig",
    "products.metrics.backend.apps.MetricsConfig",
    "products.apm.backend.apps.ApmConfig",
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
    "products.web_analytics.backend.apps.WebAnalyticsConfig",
    "products.warehouse_sources.backend.apps.WarehouseSourcesConfig",
    "products.data_tools.backend.apps.DataToolsConfig",
    "products.alerts.backend.apps.AlertsConfig",
    "products.actions.backend.apps.ActionsConfig",
    "products.autoresearch.backend.apps.AutoresearchConfig",
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
    "products.pulse.backend.apps.PulseConfig",
    "products.data_catalog.backend.apps.DataCatalogConfig",
    "products.data_quality.backend.apps.DataQualityConfig",
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
            ],
            "builtins": [
                "posthog.templatetags.posthog_assets",
                "posthog.templatetags.posthog_filters",
            ],
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
# social-auth-core reads REQUESTS_TIMEOUT in BaseAuth.request(); without it a hung self-hosted
# GitLab/OIDC provider can block a web worker forever.
SOCIAL_AUTH_REQUESTS_TIMEOUT: float = get_from_env("SOCIAL_AUTH_REQUESTS_TIMEOUT", 10.0, type_cast=float)

SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "ee.api.authentication.social_auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    # Must stay ahead of association/provisioning so a mismatched re-auth identity is rejected first
    "posthog.api.authentication.social_reauth",
    "social_core.pipeline.social_auth.associate_by_email",
    "posthog.api.signup.social_create_user",
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
    "posthog.api.authentication.social_login_notification",
    # Must stay last: it grants the step-up window, so every step that can still refuse the re-auth
    # has to have run first
    "posthog.api.authentication.social_reauth_complete",
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
# GROWTH_SIGNUP_ENRICHMENT_ENABLED and GROWTH_ICP_REENRICH_DAILY_CAP are instance settings
# (dynamic_settings.py): the env var seeds the default, the DB row is the value every pod reads.
# The internal analytics project the enrichment pipeline reads/writes bridge and mirror data
# against (products/growth/backend/enrichment). Region-defaulted to the deployment's own internal
# project (the same team split the usage report uses), so enrichment lookups never touch another
# region's project.
GROWTH_ENRICHMENT_INTERNAL_TEAM_ID = get_from_env(
    "GROWTH_ENRICHMENT_INTERNAL_TEAM_ID", 1 if (CLOUD_DEPLOYMENT or "").upper() == "EU" else 2, type_cast=int
)
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
# How long the same anomaly signature stays deduped before it re-emits telemetry / re-asserts step-up.
# Bounds a persistent anomaly to one detection per window instead of one per request, while still
# resurfacing a long-lived anomaly periodically.
RISK_REEMIT_COOLDOWN_S = get_from_env("RISK_REEMIT_COOLDOWN_S", 3600.0, type_cast=float)

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
if DEBUG:
    # Vite copies frontend/public into dist only on a production build, so in dev
    # nothing serves `/static/services/*`. Those paths aren't bundler imports — they
    # arrive as strings in API payloads (warehouse source `iconPath`, CDP destination
    # `icon_url`), so the bundler never sees them and can't rewrite them. The request
    # falls through to the SPA catch-all, the <img> is handed HTML, and every one of
    # those logos silently swaps to its error placeholder.
    #
    # DEBUG-only on purpose: in production dist already holds these files, and adding
    # a second source for 1300+ identical assets would make collectstatic warn about
    # duplicate destinations for no gain.
    STATICFILES_DIRS.append(os.path.join(BASE_DIR, "frontend/public"))

# WhiteNoise serves precompressed files when present, so this only controls collectstatic output.
if TEST:
    _staticfiles_storage_backend = "django.contrib.staticfiles.storage.StaticFilesStorage"
elif get_from_env("STATIC_PRECOMPRESS", True, type_cast=str_to_bool):
    _staticfiles_storage_backend = "whitenoise.storage.CompressedManifestStaticFilesStorage"
else:
    _staticfiles_storage_backend = "whitenoise.storage.ManifestStaticFilesStorage"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": _staticfiles_storage_backend,
    },
}
# Never emit .map.gz/.map.br: the production image deletes *.map after the
# sourcemap upload, and compressed variants would survive that cleanup and
# leak the maps under /static. Also skips pointless build-time compression
# of files that get deleted anyway.
WHITENOISE_SKIP_COMPRESS_EXTENSIONS = [*Compressor.SKIP_COMPRESS_EXTENSIONS, "map"]


def static_varies_origin(headers, path, url):
    headers["Vary"] = "Accept-Encoding, Origin"


WHITENOISE_ADD_HEADERS_FUNCTION = static_varies_origin

# Non-hashed static files (notably the posthog-js SDK bundles served to
# end-user browsers) otherwise fall back to whitenoise's 60s default and
# generate constant 304 revalidation churn (~a third of /static traffic).
# Hashed manifest assets are unaffected — whitenoise already serves those
# with far-future caching. One hour bounds how long a client that does not
# cache-bust can hold a stale SDK bundle after a release.
WHITENOISE_MAX_AGE = get_from_env("WHITENOISE_MAX_AGE", 3600, type_cast=int)

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
    "SERVERS": [
        {"url": "https://us.posthog.com", "description": "PostHog Cloud US"},
        {"url": "https://eu.posthog.com", "description": "PostHog Cloud EU"},
    ],
    "AUTHENTICATION_WHITELIST": ["posthog.auth.PersonalAPIKeyAuthentication"],
    "GET_MOCK_REQUEST": "posthog.api.documentation.build_openapi_mock_request",
    "PREPROCESSING_HOOKS": ["posthog.api.documentation.preprocess_exclude_path_format"],
    "POSTPROCESSING_HOOKS": [
        # The guard pair around postprocess_schema_enums fails the build when two
        # different choice sets resolve to one component name, which the enum hook
        # would otherwise resolve by silently dropping one schema.
        "posthog.openapi.enum_name_guard.record_enum_hashes",
        "drf_spectacular.hooks.postprocess_schema_enums",
        "posthog.openapi.enum_name_guard.check_enum_name_clashes",
        "products.dashboards.backend.widget_specs.pydantic_openapi.inject_widget_spec_pydantic_components",
        "posthog.api.documentation.custom_postprocessing_hook",
        # Runs last so it sees the final post-processed spec. Emits drf-spectacular warnings
        # for self-inconsistencies (default not in enum, required not in properties, $ref siblings)
        # so `--fail-on-warn` in `hogli build:openapi-schema` catches them in CI.
        "posthog.api.documentation.lint_spec_consistency_hook",
    ],
    "ENUM_NAME_OVERRIDES": ChoicesEnumNameOverrides(
        {
            # Most enum components are named automatically: ChoicesEnumNameOverrides walks
            # every django.db.models.Choices subclass at schema-build time and names the
            # component after the class (EarlyAccessFeature.Stage -> EarlyAccessFeatureStageEnum),
            # so defining choices as a TextChoices class is all a new enum needs. See
            # posthog/openapi/enum_names.py for the derivation and its safety rules.
            #
            # An entry below is for a choice set no class can carry, and each group states
            # why. drf-spectacular matches an entry to fields by a hash of the exact
            # (value, label) pairs, so editing values or labels on either side silently
            # detaches the entry. posthog/openapi/enum_name_guard.py and --fail-on-warn in
            # `hogli build:openapi-schema` turn the fallout into a build failure.
            # `python manage.py find_enum_collisions` diagnoses a fresh collision and
            # suggests a fix.
            #
            # Two definitions share identical (value, label) pairs but mean different
            # things. The hash cannot tell them apart, so no class is derived and the
            # entry decides the name.
            # Matches ErrorTrackingIssue severity (low/medium/high/critical).
            "TicketPriorityEnum": "products.conversations.backend.models.constants.Priority",
            # ExperimentMetricsRecalculation and ExperimentTimeseriesRecalculation both define this Status.
            "MetricsRecalculationStatusEnum": "products.experiments.backend.models.experiment.ExperimentMetricsRecalculation.Status",
            # Matches tasks' LoopVisibility (personal/team).
            "MCPAgentGrantScopeEnum": "products.mcp_store.backend.models.AGENT_GRANT_SCOPE_CHOICES",
            # BatchExport.Model and BatchExportOnDemand.Model are identical.
            "ModelEnum": "products.batch_exports.backend.models.batch_export.BatchExport.Model",
            # Matches Subscription frequency (daily/weekly/monthly).
            "RecurrenceIntervalEnum": "products.reminders.backend.models.reminder.Reminder.RecurrenceInterval",
            # Matches the messaging email channel setup provider list.
            "ScannerProviderEnum": "products.replay_vision.backend.models.replay_scanner.ScannerProvider",
            # Matches replay_vision's VisionAlertState.
            "LogsAlertConfigurationStateEnum": "products.logs.backend.models.LogsAlertConfiguration.State",
            #
            # The published name is already derived by a different choice set, so the
            # entry holds this one apart.
            "SlackSummaryCadenceEnum": ["daily", "weekly", "monthly"],
            "ExperimentStatusEnum": ["draft", "running", "paused", "exposure_frozen", "stopped"],
            "ErrorTrackingIssueStatusEnum": ["archived", "active", "resolved", "pending_release", "suppressed", "all"],
            "TaskArtifactStatusEnum": ["active", "failed"],
            #
            # The same choice set is declared in more than one product. A shared Choices
            # class would cross a product boundary, so the entry names the set centrally.
            "RunStatusEnum": ["not_started", "queued", "in_progress", "completed", "failed", "cancelled"],
            "DiagnosticSeverityEnum": ["error", "warning"],
            "InitialPermissionModeEnum": ["default", "acceptEdits", "plan", "bypassPermissions", "auto"],
            "NotificationDestinationTypeEnum": ["slack", "webhook", "teams"],
            # growth's identity-matching tier and the signals scout suggestion confidence.
            "ConfidenceTierEnum": ["low", "medium", "high"],
            #
            # The definition site is a deliberately Django-free module (facade contracts,
            # signals taxonomy), so it cannot define a models.Choices class.
            "SignalSourceProductEnum": "products.signals.backend.enums.signal_source_product_choices",
            "EngineeringAnalyticsPRStateEnum": "products.engineering_analytics.backend.facade.contracts.PRState",
            "QuarantineModeEnum": "products.engineering_analytics.backend.facade.contracts.QuarantineMode",
            "CITestRunnerEnum": "products.engineering_analytics.backend.facade.contracts.CITestRunner",
            "UserInterviewSearchDocumentTypeEnum": "products.user_interviews.backend.facade.enums.SEARCH_DOCUMENT_TYPES",
            "DesktopAccessReasonEnum": "products.tasks.backend.facade.contracts.DESKTOP_ACCESS_REASON_SCHEMA_VALUES",
            "SignalSourceProduct": "products.signals.backend.enums.SIGNAL_SOURCE_PRODUCT_VALUES",
            "SignalSourceType": "products.signals.backend.enums.SIGNAL_SOURCE_TYPE_VALUES",
            "ErrorTrackingIssueSeverityRuleEnum": ["low", "medium", "high", "critical"],
            #
            # The choices come from a typing.Literal via get_args; there is no class.
            "BlockedByEnum": ["x_frame_options", "frame_ancestors"],
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
                "metric_attribute",
                "span",
                "span_attribute",
                "span_resource_attribute",
                "revenue_analytics",
                "account_custom_property",
                "flag",
                "workflow_variable",
            ],
            "PropertyGroupTypeEnum": ["cohort", "person", "group"],
            "TaskRunBootstrapCreateRequestInitialPermissionModeEnum": [
                "default",
                "acceptEdits",
                "plan",
                "bypassPermissions",
                "auto",
                "read-only",
                "full-access",
                None,
            ],
            #
            # The choices are computed: a subset or union of another definition, a plain
            # Python enum's values, or a per-widget constant. Converting each producer to
            # a TextChoices class would delete its entry here.
            "TicketChannelFilterEnum": "products.conversations.backend.api.ticket_filters.TICKET_CHANNEL_FILTER_CHOICES",
            "TicketSlaFilterEnum": "products.conversations.backend.api.ticket_filters.TICKET_SLA_FILTER_CHOICES",
            "TicketSortOrderEnum": "products.conversations.backend.api.ticket_filters.TICKET_SORT_ORDER_CHOICES",
            "UtmIssueKindEnum": "products.marketing_analytics.backend.services.types.UTM_ISSUE_KIND_CHOICES",
            "ConversionGoalKindEnum": "products.marketing_analytics.backend.hogql_queries.constants.CONVERSION_GOAL_KIND_CHOICES",
            "ReasoningEffortEnum": ["low", "medium", "high", "xhigh", "max", "ultracode", None],
            "TaskRunReasoningEffortEnum": [
                "off",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
                "ultracode",
                None,
            ],
            "TileSpacingEnum": ["tight", "condensed", "standard", "relaxed", "wide"],
            "DataQualityCheckSeverityEnum": ["error", "warn"],
            "CanvasStateScopeEnum": ["user", "shared"],
            "CanvasKindEnum": ["freeform", "grid", "component"],
            "CanvasPlacementStatusEnum": ["pending", "generating", "live", "failed"],
            "CanvasGridColumnsEnum": [(4, 4), (6, 6), (8, 8), (10, 10), (12, 12)],
            "CanvasLayoutSchemaVersionEnum": [(1, 1)],
            "ExperimentSessionBucketEnum": ["fired_any", "no_metric_activity", "funnel_dropoff"],
            "ExperimentWatchCardKindEnum": ["behavior", "friction", "variant_only", "metric"],
            "ExperimentWatchCardStrengthEnum": ["only", "far_more", "more", "slightly_more"],
            "ExperimentWatchMultipleVariantHandlingEnum": ["exclude", "first_seen"],
            "ExperimentWatchEmptyReasonEnum": [
                "too_early",
                "no_separation",
                "no_recordings",
                "no_session_linked_exposures",
            ],
            "ReviewIssuePriorityEnum": ["must_fix", "should_fix", "consider"],
            "OtelMetricTypeEnum": ["gauge", "sum", "histogram", "exponential_histogram", "summary"],
            "VerdictEnum": ["yes", "no", "inconclusive"],
            "AIObservabilityInstrumentationCheckEnum": ["sessions", "tool_calls", "user_identity", "trace_structure"],
            "LoopTriggerTypeEnum": ["schedule", "github", "api"],
            "CustomPropertyOptionColorEnum": [f"preset-{i}" for i in range(1, 11)],
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
            "MaterializeSyncFrequencyEnum": [
                "15min",
                "30min",
                "1hour",
                "6hour",
                "12hour",
                "24hour",
                "7day",
                "30day",
            ],
            "AssigneeTypeEnum": ["user", "role"],
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
            "AdapterEnum": ["slack_message", "slack_canvas", "slack_file", "document_connector", "github_pr"],
            "ActionStepMatchingEnum": ["contains", "regex", "exact"],
            "DetailModeValueEnum": ["minimal", "detailed"],
            "RuntimeAdapterEnum": ["claude", "codex"],
            "ClaudeRuntimeAdapterEnum": ["claude"],
            "CodexRuntimeAdapterEnum": ["codex"],
            "StaffCacheKindEnum": ["evaluation", "definitions"],
            #
            # One single-value discriminator enum per dashboard widget.
            # bin/build-dashboard-widget-types.py checks these against WIDGET_SPECS.
            "ActivityEventsListWidgetTypeEnum": ["activity_events_list"],
            "ErrorTrackingListWidgetTypeEnum": ["error_tracking_list"],
            "SessionReplayListWidgetTypeEnum": ["session_replay_list"],
            "ExperimentsListWidgetTypeEnum": ["experiments_list"],
            "ExperimentResultsWidgetTypeEnum": ["experiment_results"],
            "SurveyResultsWidgetTypeEnum": ["survey_results"],
            "LogsListWidgetTypeEnum": ["logs_list"],
            "ConversationsRecentTicketsWidgetTypeEnum": ["conversations_recent_tickets"],
        }
    ),
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
                # Deploy-static source catalog (no user input or secrets reflected): several
                # hundred KB of JSON that compresses ~7x.
                "^/?api/(environments|projects)/(\\d+|@current)/external_data_sources/wizard/?$",
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
CLOUDFLARE_ACCOUNT_ID = get_from_env("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_ZONE_ID = get_from_env("CLOUDFLARE_ZONE_ID", "")
CLOUDFLARE_PROXY_KV_NAMESPACE_ID = get_from_env("CLOUDFLARE_PROXY_KV_NAMESPACE_ID", "")
CLOUDFLARE_WORKER_NAME = get_from_env("CLOUDFLARE_WORKER_NAME", "")
CLOUDFLARE_PROXY_BASE_CNAME = get_from_env("CLOUDFLARE_PROXY_BASE_CNAME", "")

# Domain Connect (automated DNS configuration)
DOMAIN_CONNECT_PRIVATE_KEY: str | None = os.getenv("DOMAIN_CONNECT_PRIVATE_KEY", "").replace("\\n", "\n") or None
DOMAIN_CONNECT_KEY_ID: str = os.getenv("DOMAIN_CONNECT_KEY_ID", "_dcpubkeyv1")

####
# CDP

# Deprecated compatibility fallback for the image CDN. New deployments should configure the
# API-specific credentials below so a publishable key can never be reused for authenticated API calls.
LOGO_DEV_TOKEN = get_from_env("LOGO_DEV_TOKEN", "")
LOGO_DEV_PUBLISHABLE_KEY = get_from_env("LOGO_DEV_PUBLISHABLE_KEY", LOGO_DEV_TOKEN)
LOGO_DEV_SECRET_KEY = get_from_env("LOGO_DEV_SECRET_KEY", "")

####
# Firecrawl (outbound page scraping, see posthog/egress/firecrawl/)
FIRECRAWL_API_KEY = get_from_env("FIRECRAWL_API_KEY", "")
# Operator ceilings on credit spend rather than Firecrawl's own limits, which the process can't see.
FIRECRAWL_EGRESS_PER_MINUTE_BUDGET = get_from_env("FIRECRAWL_EGRESS_PER_MINUTE_BUDGET", 60, type_cast=int)
FIRECRAWL_EGRESS_HOURLY_BUDGET = get_from_env("FIRECRAWL_EGRESS_HOURLY_BUDGET", 1000, type_cast=int)

####
# GitHub conditional requests (see posthog/egress/github/transport.py)
# TTL 0 disables the cache. It must outlast the slowest caller's poll interval, or every poll misses:
# warehouse GitHub schemas default to 6 hours.
GITHUB_EGRESS_CONDITIONAL_CACHE_TTL_SECONDS = get_from_env(
    "GITHUB_EGRESS_CONDITIONAL_CACHE_TTL_SECONDS", 24 * 3600, type_cast=int
)
GITHUB_EGRESS_CONDITIONAL_CACHE_MAX_BODY_BYTES = get_from_env(
    "GITHUB_EGRESS_CONDITIONAL_CACHE_MAX_BODY_BYTES", 256 * 1024, type_cast=int
)

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

# Monthly read-bytes allowance for organizations without an active subscription,
# enforced from the product-owned counter in posthog/api_queries_quota.py. 0 disables it.
API_QUERIES_FREE_TIER_READ_BYTES_LIMIT: int = get_from_env(
    "API_QUERIES_FREE_TIER_READ_BYTES_LIMIT", 50_000_000_000_000, type_cast=int
)

####
# /api/environments deprecation

# Requests to /api/environments/* are served through the equivalent /api/projects/*
# viewset via an in-process path rewrite — see posthog.middleware.EnvironmentsRewriteMiddleware.
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

# Persons list SLO sampling rate. That endpoint runs its ActorsQuery through `calculate()`,
# not `run()`, so it emits no query-service SLO events at all. It is lower volume than the
# query service and its slow tail is the point of the measurement, so it samples ten times
# higher. Same weighting rule: divide counts by `properties.sample_rate`.
PERSONS_LIST_SLO_SAMPLE_RATE = get_from_env("PERSONS_LIST_SLO_SAMPLE_RATE", 1.0 if TEST else 0.1, type_cast=float)

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

# shows the full value of the seeded dev personal API key in the UI (also requires DEBUG)
ALLOW_DEV_API_KEY_REVEAL = get_from_env("ALLOW_DEV_API_KEY_REVEAL", False, type_cast=str_to_bool)

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
HOGFLOW_BATCH_TRIGGER_LIMIT = int(get_from_env("HOGFLOW_BATCH_TRIGGER_LIMIT", 500000))
# Elevated maximum audience size, returned for teams listed in HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS.
HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED = int(get_from_env("HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED", 1000000))
# Comma-separated list of team IDs that get the elevated batch trigger limit instead of the default.
# Empty by default — everyone gets the 500k tier. Opt-in via env override for teams needing 1M.
HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS: set[int] = {
    int(team_id) for team_id in get_list(get_from_env("HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS", ""))
}

# Trust-tiered per-team caps on workflow email ("team warming"). All workflow email shares one SES
# account, so the complaint rate that account is judged on pools every team's sends. A team starts
# at tier 0 and earns the next tier by sending cleanly over time, which bounds how much damage an
# unproven team can do and keeps its early volume small enough that complaint feedback (which lags
# by hours) arrives while total volume is still low.
# The three lists are indexed by tier and must all be the same length. The top tier matches
# HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED so a fully graduated team is no more limited than it was
# before tiers existed. Adjacent tiers stay roughly 3x apart: published warmup ramps (SendGrid,
# Mailgun, Oracle) grow 25-50% per step and warn against jumps above 2x, and a promotion is an
# overnight allowance jump, so a 3x step with the utilization bar below approximates that ramp
# while keeping the tier count small enough to reason about. Two deliberate exceptions at the
# bottom: tier 0 is a 100/day probation tier for completely unproven domains (SendGrid trials
# start at 100/day, Customer.io at 200), and its hourly cap is half the daily cap rather than the
# usual fifth so a first real send does not crawl at 20 an hour. The 10x step off tier 0 is fine
# at that absolute volume.
WORKFLOWS_EMAIL_TIER_HOURLY_CAPS: list[int] = [
    int(cap)
    for cap in get_list(get_from_env("WORKFLOWS_EMAIL_TIER_HOURLY_CAPS", "50,200,600,2000,6000,20000,60000,200000"))
]
WORKFLOWS_EMAIL_TIER_DAILY_CAPS: list[int] = [
    int(cap)
    for cap in get_list(
        get_from_env("WORKFLOWS_EMAIL_TIER_DAILY_CAPS", "100,1000,3000,10000,30000,100000,300000,1000000")
    )
]
WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS: list[int] = [
    int(cap)
    for cap in get_list(
        get_from_env("WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS", "100,1000,3000,10000,30000,100000,300000,1000000")
    )
]

# Promotion bar. A team must sit at its tier for this long, actually use the tier, and keep its
# rates under the thresholds below before it moves up one step. Indexed by the tier the team is
# promoted from, clamped to the last entry, so the dwell grows with the volume at stake and a full
# climb takes the 4-6 weeks the industry treats as a complete warmup.
WORKFLOWS_EMAIL_TIER_MIN_DAYS_AT_TIER: list[int] = [
    int(days) for days in get_list(get_from_env("WORKFLOWS_EMAIL_TIER_MIN_DAYS_AT_TIER", "3,3,3,5,5,7,7,7"))
]
# Trailing window the complaint and bounce rates are measured over for promotion. 30 days is how
# the industry quotes these thresholds, and it matches the reputation surface in the workflows UI.
WORKFLOWS_EMAIL_TIER_RATE_WINDOW_DAYS = int(get_from_env("WORKFLOWS_EMAIL_TIER_RATE_WINDOW_DAYS", 30))
# Demotion reads a shorter window than promotion, so one incident stops demoting once it ages out
# of the short window instead of holding the team down for the full promotion window.
WORKFLOWS_EMAIL_TIER_DEMOTION_WINDOW_DAYS = int(get_from_env("WORKFLOWS_EMAIL_TIER_DEMOTION_WINDOW_DAYS", 7))
# After a rate-based demotion, further rate-based demotions wait this long. Without it the daily
# sweep re-reads the same dirty window every run and one incident cascades a team to the bottom.
# Keep this at least as long as the demotion window: at that length the incident that caused the
# last demotion has aged out of the window by the time demotions resume, so a second demotion can
# only come from new evidence.
WORKFLOWS_EMAIL_TIER_DEMOTION_COOLDOWN_DAYS = int(get_from_env("WORKFLOWS_EMAIL_TIER_DEMOTION_COOLDOWN_DAYS", 7))
# A team above the lowest tier that sends nothing for this long drops one tier per period. Mailbox
# providers keep about 30 days of reputation history, so a long-dormant allowance is unearned and a
# comeback blast from a stale list is exactly what the caps exist to prevent. 0 disables decay.
# The sweep tests inactivity as zero sends over WORKFLOWS_EMAIL_TIER_RATE_WINDOW_DAYS, not over this
# value, so keep the two equal. A larger value decays teams that still sent inside the rate window,
# and a smaller one waits for the rate window to clear before it decays.
WORKFLOWS_EMAIL_TIER_INACTIVITY_DECAY_DAYS = int(get_from_env("WORKFLOWS_EMAIL_TIER_INACTIVITY_DECAY_DAYS", 30))
WORKFLOWS_EMAIL_TIER_MAX_COMPLAINT_RATE = float(get_from_env("WORKFLOWS_EMAIL_TIER_MAX_COMPLAINT_RATE", 0.001))
WORKFLOWS_EMAIL_TIER_MAX_BOUNCE_RATE = float(get_from_env("WORKFLOWS_EMAIL_TIER_MAX_BOUNCE_RATE", 0.02))
# Rates are meaningless on tiny denominators: at the 0.1% complaint threshold one complaint per
# 1,000 sends IS the line, so judging a window with fewer sends turns a single complaint into a
# demotion. Below the floor a metric only counts through the absolute backstop next to it.
WORKFLOWS_EMAIL_TIER_COMPLAINT_RATE_MIN_SENDS = int(get_from_env("WORKFLOWS_EMAIL_TIER_COMPLAINT_RATE_MIN_SENDS", 1000))
WORKFLOWS_EMAIL_TIER_COMPLAINT_COUNT_BACKSTOP = int(get_from_env("WORKFLOWS_EMAIL_TIER_COMPLAINT_COUNT_BACKSTOP", 3))
WORKFLOWS_EMAIL_TIER_BOUNCE_RATE_MIN_SENDS = int(get_from_env("WORKFLOWS_EMAIL_TIER_BOUNCE_RATE_MIN_SENDS", 200))
# A team that has sent nothing has proven nothing, so promotion also needs real use of the current
# tier: this many separate days on which the team sent at least this fraction of its daily cap.
WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS = int(get_from_env("WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS", 2))
WORKFLOWS_EMAIL_TIER_MIN_DAILY_USE_RATIO = float(get_from_env("WORKFLOWS_EMAIL_TIER_MIN_DAILY_USE_RATIO", 0.5))
# app_metrics2 metric names that count as a per-workflow auto-pause for the tier decision. Empty
# means the signal contributes nothing, so the decision rests on rates and staff suspensions.
WORKFLOWS_EMAIL_TIER_AUTO_PAUSE_METRIC_NAMES: list[str] = get_list(
    get_from_env("WORKFLOWS_EMAIL_TIER_AUTO_PAUSE_METRIC_NAMES", "")
)

# Rollout mode, shared by the batch audience cap and the send-time cap:
#   "off"     - tiers are computed and stored, nothing reads them. Pre-tier behavior everywhere.
#   "shadow"  - tiers are computed and stored, and every send that a cap would have delayed is
#               logged, but no send is delayed and no audience is rejected.
#   "enforce" - caps apply.
# The email worker has its own copy, EMAIL_TEAM_SENDING_CAP_MODE in nodejs/src/cdp/config.ts,
# because it never reads Django settings. Set both sides together: this one drives the batch
# audience cap and what the workflows UI shows, and the worker's drives the send-time cap.
WORKFLOWS_EMAIL_TIER_MODE = get_from_env("WORKFLOWS_EMAIL_TIER_MODE", "off")

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
    "heatmap:write",
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

# Projected into gateway_credential.json: a JSON team_id -> tier map
# ("free"/"pro"/"enterprise") for the gateway's rate-limit bucket.
# Parsed defensively rather than with type_cast=json.loads: that runs at settings
# import, so a malformed value takes every process down at boot, while the
# consumer is written to degrade to no overrides.
try:
    AI_GATEWAY_TEAM_TIER_OVERRIDES = json.loads(get_from_env("AI_GATEWAY_TEAM_TIER_OVERRIDES", "{}"))
except ValueError:
    AI_GATEWAY_TEAM_TIER_OVERRIDES = {}

# Wizard gateway-token mint. WIZARD_GATEWAY_MINT_KEY unset disables the endpoint
# (404), which the CLI treats as "stay on the legacy gateway".
WIZARD_GATEWAY_URL = get_from_env("WIZARD_GATEWAY_URL", "")
WIZARD_GATEWAY_MINT_KEY = get_from_env("WIZARD_GATEWAY_MINT_KEY", "")
# OAuth application client ids allowed to mint: llm_gateway:read is an internal
# scope on every sandbox and agent token, so the scope alone does not identify the
# wizard. Empty refuses every mint, and blanks are filtered because a list of
# empty strings is truthy and would read as configured.
WIZARD_GATEWAY_CLIENT_IDS = [
    client_id for client_id in get_list(get_from_env("WIZARD_GATEWAY_CLIENT_IDS", "")) if client_id
]
WIZARD_GATEWAY_TOKEN_CAP_USD = get_from_env("WIZARD_GATEWAY_TOKEN_CAP_USD", "20")
# Wizard programs that may mint, each getting its own pinned product node and so
# its own per-program budget and mint quota. The list is authoritative: a program
# absent here is refused, not folded into a generic node, so listing a new program
# is required rather than optional. Mirrors the CLI's PROGRAM_REGISTRY.
WIZARD_GATEWAY_PROGRAM_IDS = get_list(get_from_env("WIZARD_GATEWAY_PROGRAM_IDS", ""))
WIZARD_GATEWAY_TOKEN_TTL_SECONDS = get_from_env("WIZARD_GATEWAY_TOKEN_TTL_SECONDS", 86400, type_cast=int)

# Exact MCP endpoints that operators explicitly allow the MCP Store to reach even
# when normal SSRF validation rejects their private/internal address. This is an
# internal dogfooding escape hatch, not a hostname or CIDR allowlist: callers must
# match one of these complete URLs byte-for-byte. Internal endpoints also bypass
# the process HTTP proxy so cluster-local traffic is not sent to Smokescreen.
# Parsed defensively like AI_GATEWAY_TEAM_TIER_OVERRIDES above: a malformed value
# must not take every process down at settings import; the URL policy degrades to
# an empty allowlist (everything internal stays blocked).
try:
    MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM: dict[str, list[str]] = json.loads(
        get_from_env("MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM", "{}")
    )
except ValueError:
    MCP_STORE_INTERNAL_ALLOWED_URLS_BY_TEAM = {}

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

# Dogfooding list for the precompute-backed web analytics trends path — teams
# here take it regardless of the `web-analytics-trends-precompute` rollout flag.
# The shared precompute enrollment gate still applies underneath.
WEB_ANALYTICS_TRENDS_PRECOMPUTE_TEAM_IDS: list[int] = [
    int(team_id) for team_id in get_list(get_from_env("WEB_ANALYTICS_TRENDS_PRECOMPUTE_TEAM_IDS", ""))
]

# Upper bound on the number of distinct precompute shapes (query cache keys) a single
# team may have live at once. Any filter combination becomes its own shape, so a
# pathological team could otherwise mint unbounded namespaces. This is a coarse backstop,
# not a quota: a team builds shapes freely until it reaches this many, after which only
# *new* shapes fall back to the live query — existing shapes keep serving and refreshing.
# Sized well above any realistic team; 0 disables the cap.
WEB_ANALYTICS_PRECOMPUTE_MAX_SHAPES_PER_TEAM: int = get_from_env(
    "WEB_ANALYTICS_PRECOMPUTE_MAX_SHAPES_PER_TEAM", 1000, type_cast=int
)

# Cohort the weekly AI path-cleaning-suggestion job runs for. Defaults to the precompute enrollment
# list (the teams "selected to test out precomputed analytics tables") so the two cohorts track each
# other unless explicitly overridden. Comma-separated env-var override, like the lists above.
WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS: list[int] = [
    int(team_id)
    for team_id in get_list(
        get_from_env(
            "WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_TEAM_IDS",
            ",".join(str(t) for t in WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS),
        )
    )
]

# Model the path-cleaning-suggestion job sends to the LLM gateway. Must be in the `web_analytics`
# product allowlist in services/llm-gateway/src/llm_gateway/products/config.py.
WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_MODEL: str = get_from_env(
    "WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_MODEL", "claude-haiku-4-5"
)

# Teams whose web analytics queries (overview, paths tile) skip the events↔sessions join
# when nothing in the query (property filters, conversion goal, test-account filters,
# sampling) constrains which sessions qualify. In that shape the join only multiplies
# cost: the sessions-side subquery is re-executed per shard of the events cluster. Trial
# rollout is per-team via comma-separated env var; defaults to the Cloud dogfooding team
# (project 2, same default as the lazy precompute lists) so the fast paths activate there
# on deploy, and to empty on self-hosted where project id 2 is an arbitrary customer.
WEB_ANALYTICS_NO_JOIN_TEAM_IDS: list[int] = [
    int(team_id)
    for team_id in get_list(get_from_env("WEB_ANALYTICS_NO_JOIN_TEAM_IDS", _LAZY_PRECOMPUTE_DEFAULT_TEAM_IDS))
]

# Percentage-of-teams rollout for the no-join fast paths, on top of the explicit
# allowlist above. Bucketing is deterministic per team (team_id % 100) so everyone
# on a team sees numbers from the same code path. 0 disables (allowlist only),
# 100 enrolls every team. Defaults to 100 on US and EU Cloud; self-hosted stays 0.
# Env var overrides in either direction and is the kill switch.
_NO_JOIN_DEFAULT_ROLLOUT_PERCENT = 100 if (CLOUD_DEPLOYMENT or "").upper() in ("US", "EU") and not TEST else 0
WEB_ANALYTICS_NO_JOIN_ROLLOUT_PERCENT: int = get_from_env(
    "WEB_ANALYTICS_NO_JOIN_ROLLOUT_PERCENT", _NO_JOIN_DEFAULT_ROLLOUT_PERCENT, type_cast=int
)


# Teams whose *filtered* web overview queries (event-property filters only) run as two
# independent scans linked by a session-id set: the events side evaluates the filters and
# collects the matching session ids, then the sessions side aggregates only over that id
# set (pushed below the per-session GROUP BY, executed once via GLOBAL IN instead of per
# shard). Allowlist only — no percent rollout yet. Defaults to the Cloud dogfooding team
# (project 2) on US Cloud, where the pattern was validated against prod; empty on EU
# (pending its ClickHouse upgrade + verification) and on self-hosted, where project id 2
# is an arbitrary customer.
_SESSION_ID_SET_DEFAULT_TEAM_IDS = "2" if (CLOUD_DEPLOYMENT or "").upper() == "US" and not TEST else ""
WEB_ANALYTICS_SESSION_ID_SET_TEAM_IDS: list[int] = [
    int(team_id)
    for team_id in get_list(get_from_env("WEB_ANALYTICS_SESSION_ID_SET_TEAM_IDS", _SESSION_ID_SET_DEFAULT_TEAM_IDS))
]
# Admission control for long-lived SSE streams: the maximum number of streams
# one worker process serves concurrently. Above the cap, sse_streaming_response()
# returns 503 with a jittered Retry-After instead of opening the stream, keeping
# processes unpinned and health probes responsive. Recovery depends on the
# client: HTTP-level retriers honor Retry-After, but a native EventSource treats
# any non-200 as fatal (readyState CLOSED, no auto-reconnect) and ignores the
# header, so those consumers must reconnect from their onerror handler.
# 0 rejects every stream (emergency lever).
SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS = get_from_env("SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS", 500, type_cast=int)
