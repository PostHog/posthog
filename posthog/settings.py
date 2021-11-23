"""
Django settings for posthog project.

Generated by 'django-admin startproject' using Django 2.2.5.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.2/ref/settings/
"""

import logging
import os
import sys
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import dj_database_url
import sentry_sdk
import structlog
from django.core.exceptions import ImproperlyConfigured
from kombu import Exchange, Queue
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from posthog.constants import AnalyticsDBMS
from posthog.utils import print_warning, str_to_bool
from posthog.version_requirement import VersionRequirement


def get_from_env(key: str, default: Any = None, *, optional: bool = False, type_cast: Optional[Callable] = None) -> Any:
    value = os.getenv(key)
    if value is None:
        if optional:
            return None
        if default is not None:
            return default
        else:
            raise ImproperlyConfigured(f'The environment variable "{key}" is required to run PostHog!')
    if type_cast is not None:
        return type_cast(value)
    return value


def get_list(text: str) -> List[str]:
    if not text:
        return []
    return [item.strip() for item in text.split(",")]


"""
There are several options:
1) running in pycharm
        second argument is "test"
2) running pytest at the CLI
        first argument is the path to pytest and ends pytest
3) running pytest using the script at /bin/tests
        first argument is the path to pytest and ends pytest
4) running in some other context (e.g. in prod)
        first argument does not end pytest
        second argument is not test

Arguments to the application will be slightly different in each case

So, in order to set test variables we need to look in slightly different places 

The /bin/tests file also runs mypy to do type checking. This needs DEBUG=1 set too

Running pytest directly does not always load django settings but sometimes needs these environment variables.
We use pytest-env to let us set environment variables from the closest pytest.ini 

We can't rely only on pytest.ini as some tests evaluate this file before its environment variables have been read
"""
runner = sys.argv[0] if len(sys.argv) >= 1 else None

if runner:
    cmd = sys.argv[1] if len(sys.argv) >= 2 else None

    if cmd == "test" or runner.endswith("pytest") or runner.endswith("mypy"):
        print("Running in test mode. Setting DEBUG and TEST environment variables.")
        os.environ["DEBUG"] = "1"
        os.environ["TEST"] = "1"

        try:
            path = sys.argv[2] if cmd == "test" else sys.argv[3]
            if path.startswith("ee"):
                print("Running EE tests. Setting clickhouse as primary database.")
                os.environ["PRIMARY_DB"] = "clickhouse"
        except IndexError:
            # there was no path, we don't want to set PRIMARY_DB
            pass


# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEBUG = get_from_env("DEBUG", False, type_cast=str_to_bool)
TEST = (
    "test" in sys.argv or sys.argv[0].endswith("pytest") or get_from_env("TEST", False, type_cast=str_to_bool)
)  # type: bool
E2E_TESTING = get_from_env(
    "E2E_TESTING", False, type_cast=str_to_bool,
)  # whether the app is currently running for E2E tests
if E2E_TESTING:
    print_warning(
        ["️WARNING! E2E_TESTING is set to `True`. This is a security vulnerability unless you are running tests."]
    )

# These flags will be force-enabled on the frontend **and OVERRIDE all** flags from `/decide`
# The features here are released, but the flags are just not yet removed from the code.
# To ignore this persisted feature flag behavior, set `PERSISTED_FEATURE_FLAGS = 0`
env_feature_flags = os.getenv("PERSISTED_FEATURE_FLAGS", "")
PERSISTED_FEATURE_FLAGS = []
if env_feature_flags != "0" and env_feature_flags.lower() != "false" and not DEBUG:
    PERSISTED_FEATURE_FLAGS = get_list(env_feature_flags) or [
        # Add hard-coded feature flags for static releases here
        "3638-trailing-wau-mau",  # pending UI/UX improvements; functionality ready
        "5440-multivariate-support",
        "6063-rename-filters",
        "4141-event-columns",
        "new-paths-ui",
        "new-paths-ui-edge-weights",
    ]


USE_PRECALCULATED_CH_COHORT_PEOPLE = not TEST
CALCULATE_X_COHORTS_PARALLEL = get_from_env("CALCULATE_X_COHORTS_PARALLEL", 2, type_cast=int)

# Instance configuration preferences
# https://posthog.com/docs/self-host/configure/environment-variables
SELF_CAPTURE = get_from_env("SELF_CAPTURE", DEBUG, type_cast=str_to_bool)
debug_queries = get_from_env("DEBUG_QUERIES", False, type_cast=str_to_bool)
disable_paid_fs = get_from_env("DISABLE_PAID_FEATURE_SHOWCASING", False, type_cast=str_to_bool)
INSTANCE_PREFERENCES = {
    "debug_queries": debug_queries,
    "disable_paid_fs": disable_paid_fs,
}

SITE_URL: str = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")

if DEBUG:
    JS_URL = os.getenv("JS_URL", "http://localhost:8234/")
else:
    JS_URL = os.getenv("JS_URL", "")

DISABLE_MMDB = get_from_env(
    "DISABLE_MMDB", TEST, type_cast=str_to_bool
)  # plugin server setting disabling GeoIP feature
PLUGINS_PREINSTALLED_URLS: List[str] = os.getenv(
    "PLUGINS_PREINSTALLED_URLS", "https://github.com/PostHog/posthog-plugin-geoip"
).split(",") if not DISABLE_MMDB else []
PLUGINS_CELERY_QUEUE = os.getenv("PLUGINS_CELERY_QUEUE", "posthog-plugins")
PLUGINS_RELOAD_PUBSUB_CHANNEL = os.getenv("PLUGINS_RELOAD_PUBSUB_CHANNEL", "reload-plugins")

# Tokens used when installing plugins, for example to get the latest commit SHA or to download private repositories.
# Used mainly to get around API limits and only if no ?private_token=TOKEN found in the plugin URL.
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)
NPM_TOKEN = os.getenv("NPM_TOKEN", None)

# This is set as a cross-domain cookie with a random value.
# Its existence is used by the toolbar to see that we are logged in.
TOOLBAR_COOKIE_NAME = "phtoolbar"

# SSL & cookie defaults
if os.getenv("SECURE_COOKIES", None) is None:
    # Default to True if in production
    secure_cookies = not DEBUG and not TEST
else:
    secure_cookies = get_from_env("SECURE_COOKIES", True, type_cast=str_to_bool)

TOOLBAR_COOKIE_SECURE = secure_cookies
SESSION_COOKIE_SECURE = secure_cookies
CSRF_COOKIE_SECURE = secure_cookies
SECURE_SSL_REDIRECT = secure_cookies
SECURE_REDIRECT_EXEMPT = [r"^_health/?"]

if not TEST:
    if os.getenv("SENTRY_DSN"):
        sentry_sdk.utils.MAX_STRING_LENGTH = 10_000_000
        # https://docs.sentry.io/platforms/python/
        sentry_logging = sentry_logging = LoggingIntegration(level=logging.INFO, event_level=None)
        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration(), sentry_logging],
            request_bodies="always",
            send_default_pii=True,
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        )

if get_from_env("DISABLE_SECURE_SSL_REDIRECT", False, type_cast=str_to_bool):
    SECURE_SSL_REDIRECT = False


# Proxy settings
IS_BEHIND_PROXY = get_from_env("IS_BEHIND_PROXY", False, type_cast=str_to_bool)
TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", None)
TRUST_ALL_PROXIES = os.getenv("TRUST_ALL_PROXIES", False)


if IS_BEHIND_PROXY:
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    if not TRUST_ALL_PROXIES and not TRUSTED_PROXIES:
        print_warning(
            (
                "️You indicated your instance is behind a proxy (IS_BEHIND_PROXY env var),",
                " but you haven't configured any trusted proxies. See",
                " https://posthog.com/docs/configuring-posthog/running-behind-proxy for details.",
            )
        )

# IP Block settings
ALLOWED_IP_BLOCKS = get_list(os.getenv("ALLOWED_IP_BLOCKS", ""))

# Clickhouse Settings
CLICKHOUSE_TEST_DB = "posthog_test"

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = CLICKHOUSE_TEST_DB if TEST else os.getenv("CLICKHOUSE_DATABASE", "default")
CLICKHOUSE_CLUSTER = os.getenv("CLICKHOUSE_CLUSTER", "posthog")
CLICKHOUSE_CA = os.getenv("CLICKHOUSE_CA", None)
CLICKHOUSE_SECURE = get_from_env("CLICKHOUSE_SECURE", not TEST and not DEBUG, type_cast=str_to_bool)
CLICKHOUSE_VERIFY = get_from_env("CLICKHOUSE_VERIFY", True, type_cast=str_to_bool)
CLICKHOUSE_REPLICATION = get_from_env("CLICKHOUSE_REPLICATION", False, type_cast=str_to_bool)
CLICKHOUSE_ENABLE_STORAGE_POLICY = get_from_env("CLICKHOUSE_ENABLE_STORAGE_POLICY", False, type_cast=str_to_bool)
CLICKHOUSE_ASYNC = get_from_env("CLICKHOUSE_ASYNC", False, type_cast=str_to_bool)

CLICKHOUSE_CONN_POOL_MIN = get_from_env("CLICKHOUSE_CONN_POOL_MIN", 20, type_cast=int)
CLICKHOUSE_CONN_POOL_MAX = get_from_env("CLICKHOUSE_CONN_POOL_MAX", 1000, type_cast=int)

CLICKHOUSE_STABLE_HOST = get_from_env("CLICKHOUSE_STABLE_HOST", CLICKHOUSE_HOST)

_clickhouse_http_protocol = "http://"
_clickhouse_http_port = "8123"
if CLICKHOUSE_SECURE:
    _clickhouse_http_protocol = "https://"
    _clickhouse_http_port = "8443"

CLICKHOUSE_HTTP_URL = f"{_clickhouse_http_protocol}{CLICKHOUSE_HOST}:{_clickhouse_http_port}/"

# Kafka configs
KAFKA_URL = os.getenv("KAFKA_URL", "kafka://kafka")
KAFKA_HOSTS_LIST = [urlparse(host).netloc for host in KAFKA_URL.split(",")]
KAFKA_HOSTS = ",".join(KAFKA_HOSTS_LIST)
KAFKA_BASE64_KEYS = get_from_env("KAFKA_BASE64_KEYS", False, type_cast=str_to_bool)

_primary_db = os.getenv("PRIMARY_DB", "postgres")
PRIMARY_DB: AnalyticsDBMS
try:
    PRIMARY_DB = AnalyticsDBMS(_primary_db)
except ValueError:
    PRIMARY_DB = AnalyticsDBMS.POSTGRES

EE_AVAILABLE = False

ACTION_EVENT_MAPPING_INTERVAL_SECONDS = get_from_env("ACTION_EVENT_MAPPING_INTERVAL_SECONDS", 300, type_cast=int)

ASYNC_EVENT_PROPERTY_USAGE = get_from_env("ASYNC_EVENT_PROPERTY_USAGE", False, type_cast=str_to_bool)
EVENT_PROPERTY_USAGE_INTERVAL_SECONDS = get_from_env(
    "ASYNC_EVENT_PROPERTY_USAGE_INTERVAL_SECONDS", 60 * 60, type_cast=int
)

UPDATE_CACHED_DASHBOARD_ITEMS_INTERVAL_SECONDS = get_from_env(
    "UPDATE_CACHED_DASHBOARD_ITEMS_INTERVAL_SECONDS", 90, type_cast=int
)

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/

DEFAULT_SECRET_KEY = "<randomly generated secret key>"

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)

ALLOWED_HOSTS = get_list(os.getenv("ALLOWED_HOSTS", "*"))

# Metrics - StatsD
STATSD_HOST = os.getenv("STATSD_HOST")
STATSD_PORT = os.getenv("STATSD_PORT", 8125)
STATSD_PREFIX = os.getenv("STATSD_PREFIX", "")
STATSD_TELEGRAF = True
STATSD_CLIENT = "statshog"
STATSD_SEPARATOR = "_"

# Whether to capture internal metrics
CAPTURE_INTERNAL_METRICS = get_from_env("CAPTURE_INTERNAL_METRICS", False, type_cast=str_to_bool)

# django-axes settings to lockout after too many attempts
AXES_ENABLED = get_from_env("AXES_ENABLED", not TEST, type_cast=str_to_bool)
AXES_HANDLER = "axes.handlers.cache.AxesCacheHandler"
AXES_FAILURE_LIMIT = int(os.getenv("AXES_FAILURE_LIMIT", 5))
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_CALLABLE = "posthog.api.authentication.axes_locked_out"
AXES_META_PRECEDENCE_ORDER = [
    "HTTP_X_FORWARDED_FOR",
    "REMOTE_ADDR",
]

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
]


MIDDLEWARE = [
    "django_structlog.middlewares.RequestMiddleware",
    "django_structlog.middlewares.CeleryMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "posthog.middleware.AllowIP",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "posthog.middleware.ToolbarCookieMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "posthog.middleware.CsrfOrKeyViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "posthog.middleware.CSVNeverCacheMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "axes.middleware.AxesMiddleware",
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
    HOOK_EVENTS: Dict[str, str] = {}
    INSTALLED_APPS.append("rest_hooks")
    INSTALLED_APPS.append("ee.apps.EnterpriseConfig")
    MIDDLEWARE.append("ee.clickhouse.middleware.CHQueries")
    EE_AVAILABLE = True

# Use django-extensions if it exists
try:
    import django_extensions  # noqa: F401
except ImportError:
    pass
else:
    INSTALLED_APPS.append("django_extensions")

INTERNAL_IPS = ["127.0.0.1", "172.18.0.1"]  # Docker IP
CORS_ORIGIN_ALLOW_ALL = True

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
            ],
        },
    },
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
SOCIAL_AUTH_FIELDS_STORED_IN_SESSION = [
    "invite_id",
    "user_name",
    "email_opt_in",
    "organization_name",
]
SOCIAL_AUTH_GITHUB_SCOPE = ["user:email"]
SOCIAL_AUTH_GITHUB_KEY = os.getenv("SOCIAL_AUTH_GITHUB_KEY")
SOCIAL_AUTH_GITHUB_SECRET = os.getenv("SOCIAL_AUTH_GITHUB_SECRET")

SOCIAL_AUTH_GITLAB_SCOPE = ["read_user"]
SOCIAL_AUTH_GITLAB_KEY = os.getenv("SOCIAL_AUTH_GITLAB_KEY")
SOCIAL_AUTH_GITLAB_SECRET = os.getenv("SOCIAL_AUTH_GITLAB_SECRET")
SOCIAL_AUTH_GITLAB_API_URL = os.getenv("SOCIAL_AUTH_GITLAB_API_URL", "https://gitlab.com")


# Support creating multiple organizations in a single instance. Requires a premium license.
MULTI_ORG_ENABLED = get_from_env("MULTI_ORG_ENABLED", False, type_cast=str_to_bool)


# See https://docs.djangoproject.com/en/3.1/ref/settings/#std:setting-DATABASE-DISABLE_SERVER_SIDE_CURSORS
DISABLE_SERVER_SIDE_CURSORS = get_from_env("USING_PGBOUNCER", False, type_cast=str_to_bool)

# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

if TEST or DEBUG:
    DATABASE_URL = os.getenv("DATABASE_URL", "postgres://localhost:5432/posthog")
else:
    DATABASE_URL = os.getenv("DATABASE_URL", "")

if DATABASE_URL:
    DATABASES = {"default": dj_database_url.config(default=DATABASE_URL, conn_max_age=600)}
    if DISABLE_SERVER_SIDE_CURSORS:
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
elif os.getenv("POSTHOG_DB_NAME"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql_psycopg2",
            "NAME": get_from_env("POSTHOG_DB_NAME"),
            "USER": os.getenv("POSTHOG_DB_USER", "postgres"),
            "PASSWORD": os.getenv("POSTHOG_DB_PASSWORD", ""),
            "HOST": os.getenv("POSTHOG_POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTHOG_POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 0,
            "DISABLE_SERVER_SIDE_CURSORS": DISABLE_SERVER_SIDE_CURSORS,
            "SSL_OPTIONS": {
                "sslmode": os.getenv("POSTHOG_POSTGRES_SSL_MODE", None),
                "sslrootcert": os.getenv("POSTHOG_POSTGRES_CLI_SSL_CA", None),
                "sslcert": os.getenv("POSTHOG_POSTGRES_CLI_SSL_CRT", None),
                "sslkey": os.getenv("POSTHOG_POSTGRES_CLI_SSL_KEY", None),
            },
        }
    }

    ssl_configurations = []
    for ssl_option, value in DATABASES["default"]["SSL_OPTIONS"].items():
        if value:
            ssl_configurations.append("{}={}".format(ssl_option, value))

    if ssl_configurations:
        ssl_configuration = "?{}".format("&".join(ssl_configurations))
    else:
        ssl_configuration = ""

    DATABASE_URL = "postgres://{}{}{}{}:{}/{}{}".format(
        DATABASES["default"]["USER"],
        ":" + DATABASES["default"]["PASSWORD"] if DATABASES["default"]["PASSWORD"] else "",
        "@" if DATABASES["default"]["USER"] or DATABASES["default"]["PASSWORD"] else "",
        DATABASES["default"]["HOST"],
        DATABASES["default"]["PORT"],
        DATABASES["default"]["NAME"],
        ssl_configuration,
    )
else:
    raise ImproperlyConfigured(
        f'The environment vars "DATABASE_URL" or "POSTHOG_DB_NAME" are absolutely required to run this software'
    )


# Broker

# The last case happens when someone upgrades Heroku but doesn't have Redis installed yet. Collectstatic gets called before we can provision Redis.
if TEST or DEBUG or (len(sys.argv) > 1 and sys.argv[1] == "collectstatic"):
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost/")
else:
    REDIS_URL = os.getenv("REDIS_URL", "")

if not REDIS_URL and get_from_env("POSTHOG_REDIS_HOST", ""):
    REDIS_URL = "redis://:{}@{}:{}/".format(
        os.getenv("POSTHOG_REDIS_PASSWORD", ""),
        os.getenv("POSTHOG_REDIS_HOST", ""),
        os.getenv("POSTHOG_REDIS_PORT", "6379"),
    )

if not REDIS_URL:
    raise ImproperlyConfigured(
        "Env var REDIS_URL or POSTHOG_REDIS_HOST is absolutely required to run this software.\n"
        "If upgrading from PostHog 1.0.10 or earlier, see here: "
        "https://posthog.com/docs/deployment/upgrading-posthog#upgrading-from-before-1011"
    )

# Only listen to the default queue "celery", unless overridden via the cli
# NB! This is set to explicitly exclude the "posthog-plugins" queue, handled by a nodejs process
CELERY_QUEUES = (Queue("celery", Exchange("celery"), "celery"),)
CELERY_DEFAULT_QUEUE = "celery"
CELERY_IMPORTS = ["ee.tasks.materialized_columns"] if PRIMARY_DB == AnalyticsDBMS.CLICKHOUSE and EE_AVAILABLE else []
CELERY_BROKER_URL = REDIS_URL  # celery connects to redis
CELERY_BEAT_MAX_LOOP_INTERVAL = 30  # sleep max 30sec before checking for new periodic events
CELERY_RESULT_BACKEND = REDIS_URL  # stores results for lookup when processing
CELERY_IGNORE_RESULT = True  # only applies to delay(), must do @shared_task(ignore_result=True) for apply_async
CELERY_RESULT_EXPIRES = timedelta(days=4)  # expire tasks after 4 days instead of the default 1
REDBEAT_LOCK_TIMEOUT = 45  # keep distributed beat lock for 45sec

CACHED_RESULTS_TTL = 7 * 24 * 60 * 60  # how long to keep cached results for
TEMP_CACHE_RESULTS_TTL = 24 * 60 * 60  # how long to keep non dashboard cached results for
SESSION_RECORDING_TTL = 30  # how long to keep session recording cache. Relatively short because cached result is used throughout the duration a session recording loads.

# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",},
]

PASSWORD_RESET_TIMEOUT = 86_400  # 1 day

# shell_plus settings
# https://django-extensions.readthedocs.io/en/latest/shell_plus.html

SHELL_PLUS_PRINT_SQL = get_from_env("PRINT_SQL", False, type_cast=str_to_bool)
SHELL_PLUS_POST_IMPORTS = [
    ("posthog.models.filters", ("Filter",)),
    ("posthog.models.property", ("Property",)),
]

if PRIMARY_DB == AnalyticsDBMS.CLICKHOUSE:
    SHELL_PLUS_POST_IMPORTS.append(("ee.clickhouse.client", ("sync_execute",)))


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
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "frontend/dist"),
]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

AUTH_USER_MODEL = "posthog.User"

LOGIN_URL = "/login"
LOGOUT_URL = "/logout"
LOGIN_REDIRECT_URL = "/"
AUTO_LOGIN = get_from_env("AUTO_LOGIN", False, type_cast=str_to_bool)
APPEND_SLASH = False
CORS_URLS_REGEX = r"^/api/.*$"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "posthog.auth.PersonalAPIKeyAuthentication",
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "PAGE_SIZE": 100,
    "EXCEPTION_HANDLER": "exceptions_hog.exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

EXCEPTIONS_HOG = {
    "EXCEPTION_REPORTING": "posthog.exceptions.exception_reporting",
}

# Email
EMAIL_ENABLED = get_from_env("EMAIL_ENABLED", True, type_cast=str_to_bool)
EMAIL_HOST = os.getenv("EMAIL_HOST", None)
EMAIL_PORT = os.getenv("EMAIL_PORT", "25")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = get_from_env("EMAIL_USE_TLS", False, type_cast=str_to_bool)
EMAIL_USE_SSL = get_from_env("EMAIL_USE_SSL", False, type_cast=str_to_bool)
DEFAULT_FROM_EMAIL = os.getenv("EMAIL_DEFAULT_FROM", os.getenv("DEFAULT_FROM_EMAIL", "root@localhost"))
EMAIL_REPLY_TO = os.getenv("EMAIL_REPLY_TO", None)

MULTI_TENANCY = False  # overriden by posthog-cloud

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "posthog",
    }
}

if TEST:
    CACHES["default"] = {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }

    import celery

    celery.current_app.conf.CELERY_ALWAYS_EAGER = True
    celery.current_app.conf.CELERY_EAGER_PROPAGATES_EXCEPTIONS = True


def add_recorder_js_headers(headers, path, url):
    if url.endswith("/recorder.js"):
        headers["Cache-Control"] = "max-age=31536000, public"


WHITENOISE_ADD_HEADERS_FUNCTION = add_recorder_js_headers

if DEBUG and not TEST:
    print_warning(
        (
            "️Environment variable DEBUG is set - PostHog is running in DEVELOPMENT MODE!",
            "Be sure to unset DEBUG if this is supposed to be a PRODUCTION ENVIRONMENT!",
        )
    )

if not DEBUG and not TEST and SECRET_KEY == DEFAULT_SECRET_KEY:
    print_warning(
        (
            "You are using the default SECRET_KEY in a production environment!",
            "For the safety of your instance, you must generate and set a unique key.",
            "More information on https://posthog.com/docs/self-host/configure/securing-posthog",
        )
    )
    sys.exit("[ERROR] Default SECRET_KEY in production. Stopping Django server…\n")


def show_toolbar(request):
    return (
        request.path.startswith("/api/")
        or request.path.startswith("/decide/")
        or request.path.startswith("/e/")
        or request.path.startswith("/__debug__")
    )


# Extend and override these settings with EE's ones
if "ee.apps.EnterpriseConfig" in INSTALLED_APPS:
    from ee.settings import *  # noqa: F401, F403


# TODO: Temporary
EMAIL_REPORTS_ENABLED: bool = get_from_env("EMAIL_REPORTS_ENABLED", False, type_cast=str_to_bool)

# Setup logging
LOGGING_FORMATTER_NAME = os.getenv("LOGGING_FORMATTER_NAME", "default")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"()": structlog.stdlib.ProcessorFormatter, "processor": structlog.dev.ConsoleRenderer(),},
        "json": {"()": structlog.stdlib.ProcessorFormatter, "processor": structlog.processors.JSONRenderer(),},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": LOGGING_FORMATTER_NAME,},
        "null": {"class": "logging.NullHandler",},
    },
    "root": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
        "django.server": {"handlers": ["null"]},  # blackhole Django server logs (this is only needed in DEV)
        "django.utils.autoreload": {
            "handlers": ["null"],
        },  # blackhole Django autoreload logs (this is only needed in DEV)
        "axes": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
        "statsd": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
    },
}

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=structlog.threadlocal.wrap_dict(dict),
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# keep in sync with plugin-server
EVENTS_DEAD_LETTER_QUEUE_STATSD_METRIC = "events_added_to_dead_letter_queue"

VERSION_REQUIREMENTS = [VersionRequirement(service="postgresql", supported_version=">=12.0.0,<15.0.0")]
