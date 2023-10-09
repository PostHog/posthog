# Web app specific settings/middleware/apps setup
import os
from datetime import timedelta
from typing import List

from corsheaders.defaults import default_headers

from posthog.settings.base_variables import BASE_DIR, DEBUG, TEST
from posthog.settings.statsd import STATSD_HOST
from posthog.settings.utils import get_from_env, get_list, str_to_bool
from posthog.utils_cors import CORS_ALLOWED_TRACING_HEADERS

# django-axes settings to lockout after too many attempts


AXES_ENABLED = get_from_env("AXES_ENABLED", not TEST, type_cast=str_to_bool)
AXES_HANDLER = "axes.handlers.cache.AxesCacheHandler"
AXES_FAILURE_LIMIT = get_from_env("AXES_FAILURE_LIMIT", 30, type_cast=int)
AXES_COOLOFF_TIME = timedelta(minutes=10)
AXES_LOCKOUT_CALLABLE = "posthog.api.authentication.axes_locked_out"
AXES_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]

# Decide rate limit setting

DECIDE_RATE_LIMIT_ENABLED = get_from_env("DECIDE_RATE_LIMIT_ENABLED", False, type_cast=str_to_bool)
DECIDE_BUCKET_CAPACITY = get_from_env("DECIDE_BUCKET_CAPACITY", type_cast=int, default=500)
DECIDE_BUCKET_REPLENISH_RATE = get_from_env("DECIDE_BUCKET_REPLENISH_RATE", type_cast=float, default=10.0)

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

# Application definition

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
    "drf_spectacular",
    "django_otp",
    "django_otp.plugins.otp_static",
    "django_otp.plugins.otp_totp",
    # 'django_otp.plugins.otp_email',  # <- if you want email capability.
    "two_factor",
    # 'two_factor.plugins.phonenumber',  # <- if you want phone number capability.
    # 'two_factor.plugins.email',  # <- if you want email capability.
    # 'two_factor.plugins.yubikey',  # <- for yubikey capability.
]


MIDDLEWARE = [
    "posthog.middleware.PrometheusBeforeMiddlewareWithTeamIds",
    "posthog.gzip_middleware.ScopedGZipMiddleware",
    "posthog.middleware.per_request_logging_context_middleware",
    "django_structlog.middlewares.RequestMiddleware",
    "django_structlog.middlewares.CeleryMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "posthog.middleware.CaptureMiddleware",
    # NOTE: we need healthcheck high up to avoid hitting middlewares that may be
    # using dependencies that the healthcheck should be checking. It should be
    # ok below the above middlewares however.
    "posthog.health.healthcheck_middleware",
    "posthog.middleware.ShortCircuitMiddleware",
    "posthog.middleware.AllowIPMiddleware",
    "google.cloud.sqlcommenter.django.middleware.SqlCommenter",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "posthog.middleware.CsrfOrKeyViewMiddleware",
    "posthog.middleware.QueryTimeCountingMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "posthog.middleware.user_logging_context_middleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "posthog.middleware.CsvNeverCacheMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "axes.middleware.AxesMiddleware",
    "posthog.middleware.AutoProjectMiddleware",
    "posthog.middleware.CHQueries",
    "posthog.middleware.PrometheusAfterMiddlewareWithTeamIds",
    "posthog.middleware.PostHogTokenCookieMiddleware",
]


if STATSD_HOST is not None:
    MIDDLEWARE.insert(0, "django_statsd.middleware.StatsdMiddleware")
    MIDDLEWARE.append("django_statsd.middleware.StatsdMiddlewareTimer")

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

# Max size of a POST body (for event ingestion)
DATA_UPLOAD_MAX_MEMORY_SIZE = 20971520  # 20 MB

ROOT_URLCONF = "posthog.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["frontend/dist", "posthog/templates", "posthog/year_in_posthog"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "posthog.wsgi.application"


# Social Auth

SOCIAL_AUTH_JSONFIELD_ENABLED = True
SOCIAL_AUTH_USER_MODEL = "posthog.User"
SOCIAL_AUTH_REDIRECT_IS_HTTPS = get_from_env("SOCIAL_AUTH_REDIRECT_IS_HTTPS", not DEBUG, type_cast=str_to_bool)

AUTHENTICATION_BACKENDS: List[str] = [
    "axes.backends.AxesBackend",
    "social_core.backends.github.GithubOAuth2",
    "social_core.backends.gitlab.GitLabOAuth2",
    "django.contrib.auth.backends.ModelBackend",
]

SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.social_auth.associate_by_email",
    "posthog.api.signup.social_create_user",
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
)

SOCIAL_AUTH_STRATEGY = "social_django.strategy.DjangoStrategy"
SOCIAL_AUTH_STORAGE = "social_django.models.DjangoStorage"
SOCIAL_AUTH_FIELDS_STORED_IN_SESSION = ["invite_id", "user_name", "email_opt_in", "organization_name"]
SOCIAL_AUTH_GITHUB_SCOPE = ["user:email"]
SOCIAL_AUTH_GITHUB_KEY = os.getenv("SOCIAL_AUTH_GITHUB_KEY")
SOCIAL_AUTH_GITHUB_SECRET = os.getenv("SOCIAL_AUTH_GITHUB_SECRET")

SOCIAL_AUTH_GITLAB_SCOPE = ["read_user"]
SOCIAL_AUTH_GITLAB_KEY = os.getenv("SOCIAL_AUTH_GITLAB_KEY")
SOCIAL_AUTH_GITLAB_SECRET = os.getenv("SOCIAL_AUTH_GITLAB_SECRET")
SOCIAL_AUTH_GITLAB_API_URL = os.getenv("SOCIAL_AUTH_GITLAB_API_URL", "https://gitlab.com")

# 2FA
TWO_FACTOR_REMEMBER_COOKIE_AGE = 60 * 60 * 24 * 30

# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}]

PASSWORD_RESET_TIMEOUT = 86_400  # 1 day

# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATIC_URL = "/static/"
STATICFILES_DIRS = [os.path.join(BASE_DIR, "frontend/dist"), os.path.join(BASE_DIR, "posthog/year_in_posthog/images")]
STATICFILES_STORAGE = "whitenoise.storage.ManifestStaticFilesStorage"

AUTH_USER_MODEL = "posthog.User"

LOGIN_URL = "/login"
LOGOUT_URL = "/logout"
LOGIN_REDIRECT_URL = "/"
APPEND_SLASH = False
CORS_URLS_REGEX = r"^/api/(?!early_access_features|surveys).*$"
CORS_ALLOW_HEADERS = default_headers + CORS_ALLOWED_TRACING_HEADERS
X_FRAME_OPTIONS = "SAMEORIGIN"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "posthog.auth.PersonalAPIKeyAuthentication",
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
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


SPECTACULAR_SETTINGS = {
    "AUTHENTICATION_WHITELIST": ["posthog.auth.PersonalAPIKeyAuthentication"],
    "PREPROCESSING_HOOKS": ["posthog.api.documentation.preprocess_exclude_path_format"],
    "POSTPROCESSING_HOOKS": ["posthog.api.documentation.custom_postprocessing_hook"],
}

EXCEPTIONS_HOG = {"EXCEPTION_REPORTING": "posthog.exceptions.exception_reporting"}


def add_recorder_js_headers(headers, path, url):
    if url.endswith("/recorder.js") and not DEBUG:
        headers["Cache-Control"] = "max-age=31536000, public"


WHITENOISE_ADD_HEADERS_FUNCTION = add_recorder_js_headers

CSRF_COOKIE_NAME = "posthog_csrftoken"

# see posthog.gzip_middleware.ScopedGZipMiddleware
# for how adding paths here can add vulnerability to the "breach" attack
GZIP_POST_RESPONSE_ALLOW_LIST = get_list(
    os.getenv(
        "GZIP_POST_RESPONSE_ALLOW_LIST",
        ",".join(
            [
                "^/?api/projects/\\d+/query/?$",
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
                "^/?api/projects/@current/property_definitions/?$",
                "^/?api/projects/\\d+/event_definitions/?$",
                "^/?api/projects/\\d+/insights/(trend|funnel)/?$",
                "^/?api/projects/\\d+/insights/?$",
                "^/?api/projects/\\d+/insights/\\d+/?$",
                "^/?api/projects/\\d+/dashboards/\\d+/?$",
                "^/?api/projects/\\d+/dashboards/?$",
                "^/?api/projects/\\d+/actions/?$",
                "^/?api/projects/\\d+/session_recordings/?$",
                "^/?api/projects/\\d+/session_recordings/.*$",
                "^/?api/projects/\\d+/session_recording_playlists/?$",
                "^/?api/projects/\\d+/session_recording_playlists/.*$",
                "^/?api/projects/\\d+/performance_events/?$",
                "^/?api/projects/\\d+/performance_events/.*$",
                "^/?api/projects/\\d+/exports/\\d+/content/?$",
                "^/?api/projects/\\d+/activity_log/important_changes/?$",
                "^/?api/projects/\\d+/uploaded_media/?$",
                "^/uploaded_media/.*$",
                "^/year_in_posthog/.*$",
                "^/api/element/stats/?$",
                "^/api/projects/\\d+/groups/property_definitions/?$",
                "^/api/projects/\\d+/cohorts/?$",
                "^/api/projects/\\d+/persons/?$",
                "^/api/organizations/@current/plugins/?$",
                "^api/projects/@current/feature_flags/my_flags/?$",
                "^/?api/projects/\\d+/query/?$",
                "^/?api/instance_status/?$",
            ]
        ),
    )
)

KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS = int(os.getenv("KAFKA_PRODUCE_ACK_TIMEOUT_SECONDS", None) or 10)

# Prometheus Django metrics settings, see
# https://github.com/korfuri/django-prometheus for more details

# We keep the number of buckets low to reduce resource usage on the Prometheus
PROMETHEUS_LATENCY_BUCKETS = [0.1, 0.3, 0.9, 2.7, 8.1] + [float("inf")]

SALT_KEY = os.getenv("SALT_KEY", "0123456789abcdefghijklmnopqrstuvwxyz")

# temporary flag to control new UUID version setting in posthog-js
# is set to v7 to test new generation but can be set to "og" to revert
POSTHOG_JS_UUID_VERSION = os.getenv("POSTHOG_JS_UUID_VERSION", "v7")
