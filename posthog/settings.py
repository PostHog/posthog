"""
Django settings for posthog project.

Generated by 'django-admin startproject' using Django 2.2.5.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.2/ref/settings/
"""

import base64
import os
import shutil
import sys
from datetime import timedelta
from distutils.util import strtobool
from typing import Dict, List, Sequence
from urllib.parse import urlparse

import dj_database_url
import sentry_sdk
from django.core.exceptions import ImproperlyConfigured
from kombu import Exchange, Queue
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration


def get_env(key):
    try:
        return os.environ[key]
    except KeyError:
        raise ImproperlyConfigured(f'The environment var "{key}" is absolutely required to run this software')


def get_list(text: str) -> List[str]:
    if not text:
        return []
    return [item.strip() for item in text.split(",")]


def get_bool_from_env(name: str, default_value: bool) -> bool:
    if name in os.environ:
        value = os.environ[name]
        try:
            return bool(strtobool(str(value)))
        except ValueError as e:
            raise ValueError(f"{value} is an invalid value for {name}, expected boolean") from e
    return default_value


def print_warning(warning_lines: Sequence[str]):
    highlight_length = min(max(map(len, warning_lines)) // 2, shutil.get_terminal_size().columns)
    print("\n".join(("", "🔻" * highlight_length, *warning_lines, "🔺" * highlight_length, "",)), file=sys.stderr)


# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEBUG = get_bool_from_env("DEBUG", False)
TEST = "test" in sys.argv or get_bool_from_env("TEST", False)  # type: bool
SELF_CAPTURE = get_bool_from_env("SELF_CAPTURE", DEBUG)
SHELL_PLUS_PRINT_SQL = get_bool_from_env("PRINT_SQL", False)

SITE_URL = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")

if DEBUG:
    JS_URL = os.environ.get("JS_URL", "http://localhost:8234/")
else:
    JS_URL = os.environ.get("JS_URL", "")

PLUGINS_INSTALL_VIA_API = get_bool_from_env("PLUGINS_INSTALL_VIA_API", True)
PLUGINS_CONFIGURE_VIA_API = PLUGINS_INSTALL_VIA_API or get_bool_from_env("PLUGINS_CONFIGURE_VIA_API", True)

PLUGINS_CELERY_QUEUE = os.environ.get("PLUGINS_CELERY_QUEUE", "posthog-plugins")
PLUGINS_RELOAD_PUBSUB_CHANNEL = os.environ.get("PLUGINS_RELOAD_PUBSUB_CHANNEL", "reload-plugins")

# This is set as a cross-domain cookie with a random value.
# Its existence is used by the toolbar to see that we are logged in.
TOOLBAR_COOKIE_NAME = "phtoolbar"

# SSL & cookie defaults
if os.environ.get("SECURE_COOKIES", None) is None:
    # Default to True if in production
    secure_cookies = not DEBUG and not TEST
else:
    secure_cookies = get_bool_from_env("SECURE_COOKIES", True)

TOOLBAR_COOKIE_SECURE = secure_cookies
SESSION_COOKIE_SECURE = secure_cookies
CSRF_COOKIE_SECURE = secure_cookies
SECURE_SSL_REDIRECT = secure_cookies

if not TEST:
    if os.environ.get("SENTRY_DSN"):
        sentry_sdk.utils.MAX_STRING_LENGTH = 10_000_000
        # https://docs.sentry.io/platforms/python/
        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration()],
            request_bodies="always",
            send_default_pii=True,
        )

if get_bool_from_env("DISABLE_SECURE_SSL_REDIRECT", False):
    SECURE_SSL_REDIRECT = False

if get_bool_from_env("IS_BEHIND_PROXY", False):
    USE_X_FORWARDED_HOST = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

ASYNC_EVENT_ACTION_MAPPING = False

if get_bool_from_env("ASYNC_EVENT_ACTION_MAPPING", False):
    ASYNC_EVENT_ACTION_MAPPING = True


# Clickhouse Settings
CLICKHOUSE_TEST_DB = "posthog_test"

CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_USERNAME = os.environ.get("CLICKHOUSE_USERNAME", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = CLICKHOUSE_TEST_DB if TEST else os.environ.get("CLICKHOUSE_DATABASE", "default")
CLICKHOUSE_CA = os.environ.get("CLICKHOUSE_CA", None)
CLICKHOUSE_SECURE = get_bool_from_env("CLICKHOUSE_SECURE", not TEST and not DEBUG)
CLICKHOUSE_VERIFY = get_bool_from_env("CLICKHOUSE_VERIFY", True)
CLICKHOUSE_REPLICATION = get_bool_from_env("CLICKHOUSE_REPLICATION", False)
CLICKHOUSE_ENABLE_STORAGE_POLICY = get_bool_from_env("CLICKHOUSE_ENABLE_STORAGE_POLICY", False)
CLICKHOUSE_ASYNC = get_bool_from_env("CLICKHOUSE_ASYNC", False)

_clickhouse_http_protocol = "http://"
_clickhouse_http_port = "8123"
if CLICKHOUSE_SECURE:
    _clickhouse_http_protocol = "https://"
    _clickhouse_http_port = "8443"

CLICKHOUSE_HTTP_URL = _clickhouse_http_protocol + CLICKHOUSE_HOST + ":" + _clickhouse_http_port + "/"

IS_HEROKU = get_bool_from_env("IS_HEROKU", False)
KAFKA_URL = os.environ.get("KAFKA_URL", "kafka://kafka")

LOG_TO_WAL = get_bool_from_env("LOG_TO_WAL", True)


# Kafka Configs

_kafka_hosts = KAFKA_URL.split(",")

KAFKA_HOSTS_LIST = []
for host in _kafka_hosts:
    url = urlparse(host)
    KAFKA_HOSTS_LIST.append(url.netloc)
KAFKA_HOSTS = ",".join(KAFKA_HOSTS_LIST)

KAFKA_BASE64_KEYS = get_bool_from_env("KAFKA_BASE64_KEYS", False)


POSTGRES = "postgres"
CLICKHOUSE = "clickhouse"

PRIMARY_DB = os.environ.get("PRIMARY_DB", POSTGRES)  # type: str

if PRIMARY_DB == CLICKHOUSE:
    TEST_RUNNER = os.environ.get("TEST_RUNNER", "ee.clickhouse.clickhouse_test_runner.ClickhouseTestRunner")
else:
    TEST_RUNNER = os.environ.get("TEST_RUNNER", "django.test.runner.DiscoverRunner")


# IP block settings
ALLOWED_IP_BLOCKS = get_list(os.environ.get("ALLOWED_IP_BLOCKS", ""))
TRUSTED_PROXIES = os.environ.get("TRUSTED_PROXIES", False)
TRUST_ALL_PROXIES = os.environ.get("TRUST_ALL_PROXIES", False)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/

DEFAULT_SECRET_KEY = "<randomly generated secret key>"

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)

ALLOWED_HOSTS = get_list(os.environ.get("ALLOWED_HOSTS", "*"))

# Metrics - StatsD
STATSD_HOST = os.environ.get("STATSD_HOST")
STATSD_PORT = os.environ.get("STATSD_PORT", 8125)
STATSD_PREFIX = os.environ.get("STATSD_PREFIX", "")

# django-axes settings to lockout after too many attempts
AXES_ENABLED = get_bool_from_env("AXES_ENABLED", True)
AXES_FAILURE_LIMIT = int(os.environ.get("AXES_FAILURE_LIMIT", 5))
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_TEMPLATE = "too_many_failed_logins.html"
AXES_META_PRECEDENCE_ORDER = [
    "HTTP_X_FORWARDED_FOR",
    "REMOTE_ADDR",
]

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
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
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "axes.middleware.AxesMiddleware",
]

if STATSD_HOST is not None:
    MIDDLEWARE.insert(0, "django_statsd.middleware.StatsdMiddleware")
    MIDDLEWARE.append("django_statsd.middleware.StatsdMiddlewareTimer")

EE_AVAILABLE = False

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

SOCIAL_AUTH_POSTGRES_JSONFIELD = True
SOCIAL_AUTH_USER_MODEL = "posthog.User"

AUTHENTICATION_BACKENDS = (
    "axes.backends.AxesBackend",
    "social_core.backends.github.GithubOAuth2",
    "social_core.backends.gitlab.GitLabOAuth2",
    "social_core.backends.google.GoogleOAuth2",
    "django.contrib.auth.backends.ModelBackend",
)

SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.social_auth.associate_by_email",
    "posthog.urls.social_create_user",
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
)

SOCIAL_AUTH_STRATEGY = "social_django.strategy.DjangoStrategy"
SOCIAL_AUTH_STORAGE = "social_django.models.DjangoStorage"
SOCIAL_AUTH_FIELDS_STORED_IN_SESSION = ["invite_id", "user_name", "company_name", "email_opt_in"]

SOCIAL_AUTH_GITHUB_SCOPE = ["user:email"]
SOCIAL_AUTH_GITHUB_KEY = os.environ.get("SOCIAL_AUTH_GITHUB_KEY")
SOCIAL_AUTH_GITHUB_SECRET = os.environ.get("SOCIAL_AUTH_GITHUB_SECRET")

SOCIAL_AUTH_GITLAB_SCOPE = ["read_user"]
SOCIAL_AUTH_GITLAB_KEY = os.environ.get("SOCIAL_AUTH_GITLAB_KEY")
SOCIAL_AUTH_GITLAB_SECRET = os.environ.get("SOCIAL_AUTH_GITLAB_SECRET")
SOCIAL_AUTH_GITLAB_API_URL = os.environ.get("SOCIAL_AUTH_GITLAB_API_URL", "https://gitlab.com")

# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

if TEST or DEBUG:
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://localhost:5432/posthog")
else:
    DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    DATABASES = {"default": dj_database_url.config(default=DATABASE_URL, conn_max_age=600)}
elif os.environ.get("POSTHOG_DB_NAME"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql_psycopg2",
            "NAME": get_env("POSTHOG_DB_NAME"),
            "USER": os.environ.get("POSTHOG_DB_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTHOG_DB_PASSWORD", ""),
            "HOST": os.environ.get("POSTHOG_POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTHOG_POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 0,
        }
    }
    DATABASE_URL = "postgres://{}{}{}{}:{}/{}".format(
        DATABASES["default"]["USER"],
        ":" + DATABASES["default"]["PASSWORD"] if DATABASES["default"]["PASSWORD"] else "",
        "@" if DATABASES["default"]["USER"] or DATABASES["default"]["PASSWORD"] else "",
        DATABASES["default"]["HOST"],
        DATABASES["default"]["PORT"],
        DATABASES["default"]["NAME"],
    )
else:
    raise ImproperlyConfigured(
        f'The environment vars "DATABASE_URL" or "POSTHOG_DB_NAME" are absolutely required to run this software'
    )

# See https://docs.djangoproject.com/en/3.1/ref/settings/#std:setting-DATABASE-DISABLE_SERVER_SIDE_CURSORS
DISABLE_SERVER_SIDE_CURSORS = get_bool_from_env("USING_PGBOUNCER", False)

# Broker

# The last case happens when someone upgrades Heroku but doesn't have Redis installed yet. Collectstatic gets called before we can provision Redis.
if TEST or DEBUG or (len(sys.argv) > 1 and sys.argv[1] == "collectstatic"):
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost/")
else:
    REDIS_URL = os.environ.get("REDIS_URL", "")

if not REDIS_URL and os.environ.get("POSTHOG_REDIS_HOST", ""):
    REDIS_URL = "redis://:{}@{}:{}/".format(
        os.environ.get("POSTHOG_REDIS_PASSWORD", ""),
        os.environ.get("POSTHOG_REDIS_HOST", ""),
        os.environ.get("POSTHOG_REDIS_PORT", "6379"),
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
CELERY_IMPORTS = ["posthog.tasks.webhooks"]  # required to avoid circular import

if PRIMARY_DB == CLICKHOUSE:
    try:
        from ee.apps import EnterpriseConfig  # noqa: F401
    except ImportError:
        pass
    else:
        CELERY_IMPORTS.append("ee.tasks.webhooks_ee")

CELERY_BROKER_URL = REDIS_URL  # celery connects to redis
CELERY_BEAT_MAX_LOOP_INTERVAL = 30  # sleep max 30sec before checking for new periodic events
CELERY_RESULT_BACKEND = REDIS_URL  # stores results for lookup when processing
CELERY_IGNORE_RESULT = True  # only applies to delay(), must do @shared_task(ignore_result=True) for apply_async
REDBEAT_LOCK_TIMEOUT = 45  # keep distributed beat lock for 45sec

CACHED_RESULTS_TTL = 24 * 60 * 60  # how long to keep cached results for

# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",},
]


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
    "EXCEPTION_HANDLER": "exceptions_hog.exception_handler",
    "PAGE_SIZE": 100,
}

EXCEPTIONS_HOG = {
    "EXCEPTION_REPORTING": "posthog.utils.exception_reporting",
}

# Email
EMAIL_ENABLED = get_bool_from_env("EMAIL_ENABLED", True)
EMAIL_HOST = os.environ.get("EMAIL_HOST", None)
EMAIL_PORT = os.environ.get("EMAIL_PORT", "25")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = get_bool_from_env("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = get_bool_from_env("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = os.environ.get("EMAIL_DEFAULT_FROM", os.environ.get("DEFAULT_FROM_EMAIL", "root@localhost"))

MULTI_TENANCY = False  # overriden by posthog-production

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

if DEBUG and not TEST:
    print_warning(
        (
            "️Environment variable DEBUG is set - PostHog is running in DEVELOPMENT MODE!",
            "Be sure to unset DEBUG if this is supposed to be a PRODUCTION ENVIRONMENT!",
        )
    )

    # Load debug_toolbar if we can
    try:
        import debug_toolbar  # noqa: F401
    except ImportError:
        pass
    else:
        INSTALLED_APPS.append("debug_toolbar")
        MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")

if not DEBUG and not TEST and SECRET_KEY == DEFAULT_SECRET_KEY:
    print_warning(
        (
            "You are using the default SECRET_KEY in a production environment!",
            "For the safety of your instance, you must generate and set a unique key.",
            "More information on https://posthog.com/docs/deployment/securing-posthog#secret-key",
        )
    )
    sys.exit("[ERROR] Default SECRET_KEY in production. Stopping Django server…\n")


def show_toolbar(request):
    return request.path.startswith("/api/") or request.path.startswith("/decide/") or request.path.startswith("/e/")


DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": "posthog.settings.show_toolbar",
}

# Extend and override these settings with EE's ones
if "ee.apps.EnterpriseConfig" in INSTALLED_APPS:
    from ee.settings import *  # noqa: F401, F403


# TODO: Temporary
EMAIL_REPORTS_ENABLED: bool = get_bool_from_env("EMAIL_REPORTS_ENABLED", False)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler",},},
    "root": {"handlers": ["console"], "level": "WARNING",},
    "loggers": {
        "django": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "WARNING"), "propagate": True,},
    },
}
