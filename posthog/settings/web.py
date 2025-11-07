# Web app specific settings/middleware/apps setup
import os
from datetime import timedelta

import structlog
from corsheaders.defaults import default_headers

from posthog.scopes import get_scope_descriptions
from posthog.settings.base_variables import BASE_DIR, DEBUG, TEST
from posthog.settings.utils import get_from_env, get_list, str_to_bool
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
    "products.early_access_features.backend.apps.EarlyAccessFeaturesConfig",
    "products.tasks.backend.apps.TasksConfig",
    "products.links.backend.apps.LinksConfig",
    "products.revenue_analytics.backend.apps.RevenueAnalyticsConfig",
    "products.user_interviews.backend.apps.UserInterviewsConfig",
    "products.llm_analytics.backend.apps.LlmAnalyticsConfig",
    "products.endpoints.backend.apps.EndpointsConfig",
    "products.marketing_analytics.backend.apps.MarketingAnalyticsConfig",
    "products.error_tracking.backend.apps.ErrorTrackingConfig",
    "products.notebooks.backend.apps.NotebooksConfig",
    "products.data_warehouse.backend.apps.DataWarehouseConfig",
    "products.desktop_recordings.backend.apps.DesktopRecordingsConfig",
    "products.live_debugger.backend.apps.LiveDebuggerConfig",
]

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",  # makes sure that whitenoise handles static files in development
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
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
    # NOTE: we need healthcheck high up to avoid hitting middlewares that may be
    # using dependencies that the healthcheck should be checking. It should be
    # ok below the above middlewares however.
    "posthog.health.healthcheck_middleware",
    "posthog.middleware.ShortCircuitMiddleware",
    "posthog.middleware.AllowIPMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "posthog.middleware.CSPMiddleware",
    "django.middleware.common.CommonMiddleware",
    "posthog.middleware.CsrfOrKeyViewMiddleware",
    "posthog.middleware.QueryTimeCountingMiddleware",
    "posthog.middleware.OverridableAuthenticationMiddleware",
    "posthog.middleware.SocialAuthExceptionMiddleware",
    "posthog.middleware.SessionAgeMiddleware",
    "posthog.middleware.ActivityLoggingMiddleware",
    "posthog.middleware.user_logging_context_middleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "posthog.middleware.AutoLogoutImpersonateMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
            ]
        },
    }
]

WSGI_APPLICATION = "posthog.wsgi.application"


####
# Authentication

AUTHENTICATION_BACKENDS: list[str] = [
    "axes.backends.AxesBackend",
    "social_core.backends.github.GithubOAuth2",
    "social_core.backends.gitlab.GitLabOAuth2",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_USER_MODEL = "posthog.User"

LOGIN_URL = "/login"
LOGOUT_URL = "/logout"
LOGIN_REDIRECT_URL = "/"
APPEND_SLASH = False
CORS_URLS_REGEX = r"^(/site_app/|/array/|/static/|/api/(?!early_access_features|surveys|web_experiments).*$)"
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
SESSION_COOKIE_AGE = get_from_env("SESSION_COOKIE_AGE", 60 * 60 * 24 * 14, type_cast=int)

# For sensitive actions we have an additional permission (default 2 hour)
SESSION_SENSITIVE_ACTIONS_AGE = get_from_env("SESSION_SENSITIVE_ACTIONS_AGE", 60 * 60 * 2, type_cast=int)

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
CAN_LOGIN_AS = lambda request, target_user: request.user.is_staff and not target_user.is_staff

SESSION_COOKIE_CREATED_AT_KEY = get_from_env("SESSION_COOKIE_CREATED_AT_KEY", "session_created_at")

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

PASSWORD_RESET_TIMEOUT = 86_400  # 1 day

####
# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True

####
# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATIC_URL = "/static/"
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "frontend/dist"),
]
STATICFILES_STORAGE = "whitenoise.storage.ManifestStaticFilesStorage"


def static_varies_origin(headers, path, url):
    headers["Vary"] = "Accept-Encoding, Origin"


WHITENOISE_ADD_HEADERS_FUNCTION = static_varies_origin

####
# REST framework

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["posthog.auth.SessionAuthentication"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["posthog.renderers.SafeJSONRenderer"],
    "PAGE_SIZE": 100,
    "EXCEPTION_HANDLER": "exceptions_hog.exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
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
    "AUTHENTICATION_WHITELIST": ["posthog.auth.PersonalAPIKeyAuthentication"],
    "PREPROCESSING_HOOKS": ["posthog.api.documentation.preprocess_exclude_path_format"],
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "posthog.api.documentation.custom_postprocessing_hook",
    ],
    "ENUM_NAME_OVERRIDES": {
        "DashboardRestrictionLevel": "posthog.models.dashboard.Dashboard.RestrictionLevel",
        "OrganizationMembershipLevel": "posthog.models.organization.OrganizationMembership.Level",
        "SurveyType": "posthog.models.surveys.survey.Survey.SurveyType",
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
                "^/api/(environments|projects)/\\d+/groups/property_definitions/?$",
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

####
# CDP

LOGO_DEV_TOKEN = get_from_env("LOGO_DEV_TOKEN", "")

####
# /decide

# Decide rate limit setting
DECIDE_RATE_LIMIT_ENABLED = get_from_env("DECIDE_RATE_LIMIT_ENABLED", False, type_cast=str_to_bool)
DECIDE_BUCKET_CAPACITY = get_from_env("DECIDE_BUCKET_CAPACITY", type_cast=int, default=500)
DECIDE_BUCKET_REPLENISH_RATE = get_from_env("DECIDE_BUCKET_REPLENISH_RATE", type_cast=float, default=10.0)

# This is a list of team-ids that are prevented from using the /decide endpoint
# until they fix an issue with their feature flags causing instability in posthog.
DECIDE_SHORT_CIRCUITED_TEAM_IDS = [0]

# Decide db settings
DECIDE_SKIP_POSTGRES_FLAGS = get_from_env("DECIDE_SKIP_POSTGRES_FLAGS", False, type_cast=str_to_bool)

# Decide billing analytics
DECIDE_BILLING_SAMPLING_RATE = get_from_env("DECIDE_BILLING_SAMPLING_RATE", 0.1, type_cast=float)
DECIDE_BILLING_ANALYTICS_TOKEN = get_from_env("DECIDE_BILLING_ANALYTICS_TOKEN", None, type_cast=str, optional=True)

# Decide regular request analytics
# Takes 3 possible formats, all separated by commas:
# A number: "2"
# A range: "2:5" -- represents team IDs 2, 3, 4, 5
# The string "all" -- represents all team IDs
DECIDE_TRACK_TEAM_IDS = get_list(os.getenv("DECIDE_TRACK_TEAM_IDS", ""))

# Decide skip hash key overrides
DECIDE_SKIP_HASH_KEY_OVERRIDE_WRITES = get_from_env(
    "DECIDE_SKIP_HASH_KEY_OVERRIDE_WRITES", False, type_cast=str_to_bool
)

# if `true` we disable session replay if over quota
DECIDE_SESSION_REPLAY_QUOTA_CHECK = get_from_env("DECIDE_SESSION_REPLAY_QUOTA_CHECK", False, type_cast=str_to_bool)

# if `true` we disable feature flags if over quota
DECIDE_FEATURE_FLAG_QUOTA_CHECK = get_from_env("DECIDE_FEATURE_FLAG_QUOTA_CHECK", False, type_cast=str_to_bool)

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

####
# /capture

KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS = int(os.getenv("KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS", None) or 10)

####
# /query

# if `true` we highly increase the rate limit on /query endpoint and limit the number of concurrent queries
API_QUERIES_ENABLED = get_from_env("API_QUERIES_ENABLED", False, type_cast=str_to_bool)


####
# Livestream

# Passed to the frontend for the web app to know where to connect to
LIVESTREAM_HOST = get_from_env("LIVESTREAM_HOST", "")

####
# Local dev

# disables frontend side navigation hooks to make hot-reload work seamlessly
DEV_DISABLE_NAVIGATION_HOOKS = get_from_env("DEV_DISABLE_NAVIGATION_HOOKS", False, type_cast=bool)

####
# Random/temporary
# Everything that is supposed to be removed eventually

# temporary flag to control new UUID version setting in posthog-js
# is set to v7 to test new generation but can be set to "og" to revert
POSTHOG_JS_UUID_VERSION = os.getenv("POSTHOG_JS_UUID_VERSION", "v7")

# Feature flag to enable HogFunctions daily digest email for specific teams
# Comma-separated list of team IDs that should receive the digest
HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS = get_list(get_from_env("HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS", ""))


####
# OAuth

OIDC_RSA_PRIVATE_KEY = os.getenv("OIDC_RSA_PRIVATE_KEY", "").replace("\\n", "\n")


OAUTH_EXPIRED_TOKEN_RETENTION_PERIOD = 60 * 60 * 24 * 30  # 30 days

OAUTH2_PROVIDER = {
    "OIDC_ENABLED": True,
    "PKCE_REQUIRED": True,  # We require PKCE for all OAuth flows - including confidential clients
    "OIDC_RSA_PRIVATE_KEY": OIDC_RSA_PRIVATE_KEY,
    "SCOPES": {
        "openid": "OpenID Connect scope",
        "profile": "Access to user's profile",
        "email": "Access to user's email address",
        "*": "Full access to all scopes",
        **get_scope_descriptions(),
    },
    # Allow both http and https schemes to support localhost callbacks
    # Security validation in OAuthApplication.clean() ensures http is only allowed for loopback addresses (localhost, 127.0.0.0/8) in production
    "ALLOWED_REDIRECT_URI_SCHEMES": ["http", "https"],
    "AUTHORIZATION_CODE_EXPIRE_SECONDS": 60
    * 5,  # client has 5 minutes to complete the OAuth flow before the authorization code expires
    "DEFAULT_SCOPES": ["openid"],
    "ACCESS_TOKEN_GENERATOR": "posthog.models.utils.generate_random_oauth_access_token",
    "REFRESH_TOKEN_GENERATOR": "posthog.models.utils.generate_random_oauth_refresh_token",
    "OAUTH2_VALIDATOR_CLASS": "posthog.api.oauth.OAuthValidator",
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

# Sharing configuration settings
SHARING_TOKEN_GRACE_PERIOD_SECONDS = 60 * 5  # 5 minutes

SURVEYS_API_USE_HYPERCACHE_TOKENS = get_list(os.getenv("SURVEYS_API_USE_HYPERCACHE_TOKENS", ""))
SURVEYS_API_USE_REMOTE_CONFIG_COMPARE = get_from_env(
    "SURVEYS_API_USE_REMOTE_CONFIG_COMPARE", False, type_cast=str_to_bool
)
