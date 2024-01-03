import json
import os
from typing import List
from urllib.parse import urlparse

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from posthog.settings.base_variables import DEBUG, IS_COLLECT_STATIC, TEST
from posthog.settings.utils import get_from_env, get_list, str_to_bool

# See https://docs.djangoproject.com/en/3.2/ref/settings/#std:setting-DATABASE-DISABLE_SERVER_SIDE_CURSORS
DISABLE_SERVER_SIDE_CURSORS = get_from_env("USING_PGBOUNCER", False, type_cast=str_to_bool)
# See https://docs.djangoproject.com/en/3.2/ref/settings/#std:setting-DATABASE-DISABLE_SERVER_SIDE_CURSORS
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# Configuration for sqlcommenter
SQLCOMMENTER_WITH_FRAMEWORK = False

# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

JOB_QUEUE_GRAPHILE_URL = os.getenv("JOB_QUEUE_GRAPHILE_URL")


def postgres_config(host: str) -> dict:
    """Generate the config map we need for a postgres database.

    Generally all our postgres databases will need the same config - replicas are identical other than host.

    Parameters:
        host (str): The host to connect to

    Returns:
        dict: The config, to be set in django DATABASES
    """

    return {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": get_from_env("POSTHOG_DB_NAME"),
        "USER": os.getenv("POSTHOG_DB_USER", "postgres"),
        "PASSWORD": os.getenv("POSTHOG_DB_PASSWORD", ""),
        "HOST": host,
        "PORT": os.getenv("POSTHOG_POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 0,
        "DISABLE_SERVER_SIDE_CURSORS": DISABLE_SERVER_SIDE_CURSORS,
        "SSL_OPTIONS": {
            "sslmode": os.getenv("POSTHOG_POSTGRES_SSL_MODE", None),
            "sslrootcert": os.getenv("POSTHOG_POSTGRES_CLI_SSL_CA", None),
            "sslcert": os.getenv("POSTHOG_POSTGRES_CLI_SSL_CRT", None),
            "sslkey": os.getenv("POSTHOG_POSTGRES_CLI_SSL_KEY", None),
        },
        "TEST": {
            "MIRROR": "default",
        },
    }


if TEST or DEBUG:
    PG_HOST = os.getenv("PGHOST", "localhost")
    PG_USER = os.getenv("PGUSER", "posthog")
    PG_PASSWORD = os.getenv("PGPASSWORD", "posthog")
    PG_PORT = os.getenv("PGPORT", "5432")
    PG_DATABASE = os.getenv("PGDATABASE", "posthog")
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        f"postgres://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}",
    )
else:
    DATABASE_URL = os.getenv("DATABASE_URL", "")

if DATABASE_URL:
    DATABASES = {"default": dj_database_url.config(default=DATABASE_URL, conn_max_age=0)}

    if DISABLE_SERVER_SIDE_CURSORS:
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

elif os.getenv("POSTHOG_DB_NAME"):
    DATABASES = {"default": postgres_config(os.getenv("POSTHOG_POSTGRES_HOST", "localhost"))}

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

# Configure the database which will be used as a read replica.
# This should have all the same config as our main writer DB, just use a different host.
# Our database router will point here.
read_host = os.getenv("POSTHOG_POSTGRES_READ_HOST")
if read_host:
    DATABASES["replica"] = postgres_config(read_host)
    DATABASE_ROUTERS = ["posthog.dbrouter.ReplicaRouter"]

if JOB_QUEUE_GRAPHILE_URL:
    DATABASES["graphile"] = dj_database_url.config(default=JOB_QUEUE_GRAPHILE_URL, conn_max_age=600)


# Opt-in to using the read replica
# Models using this will likely see better query latency, and better performance.
# Immediately reading after writing may not return consistent data if done in <100ms
# Pass in model classnames that should use the read replica

# Note: Regardless of settings, cursor usage will use the default DB unless otherwise specified.
# Database routers route models!
replica_opt_in = os.environ.get("READ_REPLICA_OPT_IN", "")
READ_REPLICA_OPT_IN: list[str] = get_list(replica_opt_in)


# Clickhouse Settings
CLICKHOUSE_TEST_DB = "posthog_test"

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_OFFLINE_CLUSTER_HOST = os.getenv("CLICKHOUSE_OFFLINE_CLUSTER_HOST", None)
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = CLICKHOUSE_TEST_DB if TEST else os.getenv("CLICKHOUSE_DATABASE", "default")
CLICKHOUSE_CLUSTER = os.getenv("CLICKHOUSE_CLUSTER", "posthog")
CLICKHOUSE_CA = os.getenv("CLICKHOUSE_CA", None)
CLICKHOUSE_SECURE = get_from_env("CLICKHOUSE_SECURE", not TEST and not DEBUG, type_cast=str_to_bool)
CLICKHOUSE_VERIFY = get_from_env("CLICKHOUSE_VERIFY", True, type_cast=str_to_bool)
CLICKHOUSE_ENABLE_STORAGE_POLICY = get_from_env("CLICKHOUSE_ENABLE_STORAGE_POLICY", False, type_cast=str_to_bool)

CLICKHOUSE_CONN_POOL_MIN = get_from_env("CLICKHOUSE_CONN_POOL_MIN", 20, type_cast=int)
CLICKHOUSE_CONN_POOL_MAX = get_from_env("CLICKHOUSE_CONN_POOL_MAX", 1000, type_cast=int)

CLICKHOUSE_STABLE_HOST = get_from_env("CLICKHOUSE_STABLE_HOST", CLICKHOUSE_HOST)
# If enabled, some queries will use system.cluster table to query each shard
CLICKHOUSE_ALLOW_PER_SHARD_EXECUTION = get_from_env(
    "CLICKHOUSE_ALLOW_PER_SHARD_EXECUTION", False, type_cast=str_to_bool
)

try:
    CLICKHOUSE_PER_TEAM_SETTINGS = json.loads(os.getenv("CLICKHOUSE_PER_TEAM_SETTINGS", "{}"))
except Exception:
    CLICKHOUSE_PER_TEAM_SETTINGS = {}

_clickhouse_http_protocol = "http://"
_clickhouse_http_port = "8123"
if CLICKHOUSE_SECURE:
    _clickhouse_http_protocol = "https://"
    _clickhouse_http_port = "8443"

CLICKHOUSE_HTTP_URL = f"{_clickhouse_http_protocol}{CLICKHOUSE_HOST}:{_clickhouse_http_port}/"

CLICKHOUSE_OFFLINE_HTTP_URL = f"{_clickhouse_http_protocol}{CLICKHOUSE_OFFLINE_CLUSTER_HOST}:{_clickhouse_http_port}/"

if TEST or DEBUG or os.getenv("CLICKHOUSE_OFFLINE_CLUSTER_HOST", None) is None:
    # When testing, there is no offline cluster.
    # Also in EU, there is no offline cluster.
    CLICKHOUSE_OFFLINE_HTTP_URL = CLICKHOUSE_HTTP_URL


READONLY_CLICKHOUSE_USER = os.getenv("READONLY_CLICKHOUSE_USER", None)
READONLY_CLICKHOUSE_PASSWORD = os.getenv("READONLY_CLICKHOUSE_PASSWORD", None)


def _parse_kafka_hosts(hosts_string: str) -> List[str]:
    hosts = []
    for host in hosts_string.split(","):
        if "://" in host:
            hosts.append(urlparse(host).netloc)
        else:
            hosts.append(host)

    # We don't want empty strings
    return [host for host in hosts if host]


# URL(s) used by Kafka clients/producers - KEEP IN SYNC WITH plugin-server/src/config/config.ts
# We prefer KAFKA_HOSTS over KAFKA_URL (which used to be used)
KAFKA_HOSTS = _parse_kafka_hosts(os.getenv("KAFKA_HOSTS", "") or os.getenv("KAFKA_URL", "") or "kafka:9092")
# Dedicated kafka hosts for session recordings
SESSION_RECORDING_KAFKA_HOSTS = _parse_kafka_hosts(os.getenv("SESSION_RECORDING_KAFKA_HOSTS", "")) or KAFKA_HOSTS
# Kafka broker host(s) that is used by clickhouse for ingesting messages.
# Useful if clickhouse is hosted outside the cluster.
KAFKA_HOSTS_FOR_CLICKHOUSE = _parse_kafka_hosts(os.getenv("KAFKA_URL_FOR_CLICKHOUSE", "")) or KAFKA_HOSTS

# can set ('gzip', 'snappy', 'lz4', 'zstd' None)
# NB if you want to set a compression you need to install it... the producer compresses not kafka
# so, at time of writing only 'gzip' and None/'uncompressed' are available
SESSION_RECORDING_KAFKA_COMPRESSION = os.getenv("SESSION_RECORDING_KAFKA_COMPRESSION", None)

# To support e.g. Multi-tenanted plans on Heroko, we support specifying a prefix for
# Kafka Topics. See
# https://devcenter.heroku.com/articles/multi-tenant-kafka-on-heroku#differences-to-dedicated-kafka-plans
# for details.
KAFKA_PREFIX = os.getenv("KAFKA_PREFIX", "")

KAFKA_BASE64_KEYS = get_from_env("KAFKA_BASE64_KEYS", False, type_cast=str_to_bool)

SESSION_RECORDING_KAFKA_MAX_REQUEST_SIZE_BYTES: int = get_from_env(
    "SESSION_RECORDING_KAFKA_MAX_REQUEST_SIZE_BYTES",
    1024 * 1024,  # 1MB
    type_cast=int,
)

KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", None)
SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL = os.getenv(
    "SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL", KAFKA_SECURITY_PROTOCOL
)
KAFKA_SASL_MECHANISM = os.getenv("KAFKA_SASL_MECHANISM", None)
KAFKA_SASL_USER = os.getenv("KAFKA_SASL_USER", None)
KAFKA_SASL_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD", None)

SUFFIX = "_test" if TEST else ""

KAFKA_EVENTS_PLUGIN_INGESTION: str = (
    f"{KAFKA_PREFIX}events_plugin_ingestion{SUFFIX}"  # can be overridden in settings.py
)

# Topic to write events to between clickhouse
KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC: str = os.getenv(
    "KAFKA_EVENTS_PLUGIN_INGESTION_TOPIC", KAFKA_EVENTS_PLUGIN_INGESTION
)

# A list of tokens for which events should be sent to the historical topic
# TODO: possibly remove this and replace with something that provides the
# separation of concerns between realtime and historical ingestion but without
# needing to have a deploy.
TOKENS_HISTORICAL_DATA = os.getenv("TOKENS_HISTORICAL_DATA", "").split(",")

# The last case happens when someone upgrades Heroku but doesn't have Redis installed yet. Collectstatic gets called before we can provision Redis.
if TEST or DEBUG or IS_COLLECT_STATIC:
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost/")
else:
    REDIS_URL = os.getenv("REDIS_URL", "")

if not REDIS_URL and get_from_env("POSTHOG_REDIS_HOST", ""):
    REDIS_URL = "redis://:{}@{}:{}/".format(
        os.getenv("POSTHOG_REDIS_PASSWORD", ""),
        os.getenv("POSTHOG_REDIS_HOST", ""),
        os.getenv("POSTHOG_REDIS_PORT", "6379"),
    )

SESSION_RECORDING_REDIS_URL = REDIS_URL

if get_from_env("POSTHOG_SESSION_RECORDING_REDIS_HOST", ""):
    SESSION_RECORDING_REDIS_URL = "redis://{}:{}/".format(
        os.getenv("POSTHOG_SESSION_RECORDING_REDIS_HOST", ""),
        os.getenv("POSTHOG_SESSION_RECORDING_REDIS_PORT", "6379"),
    )


if not REDIS_URL:
    raise ImproperlyConfigured(
        "Env var REDIS_URL or POSTHOG_REDIS_HOST is absolutely required to run this software.\n"
        "If upgrading from PostHog 1.0.10 or earlier, see here: "
        "https://posthog.com/docs/deployment/upgrading-posthog#upgrading-from-before-1011"
    )

# Controls whether the TolerantZlibCompressor is used for Redis compression when writing to Redis.
# The TolerantZlibCompressor is a drop-in replacement for the standard Django ZlibCompressor that
# can cope with compressed and uncompressed reading at the same time
USE_REDIS_COMPRESSION = get_from_env("USE_REDIS_COMPRESSION", False, type_cast=str_to_bool)

# AWS ElastiCache supports "reader" endpoints.
# See "Finding a Redis (Cluster Mode Disabled) Cluster's Endpoints (Console)"
# on https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/Endpoints.html#Endpoints.Find.Redis
# A reader endpoint distributes read-only connections across all replicas in the cluster.
# ElastiCache manages updating which nodes are used if a replica is failed-over to primary
# so that we don't have to worry about changing config.
REDIS_READER_URL = os.getenv("REDIS_READER_URL", None)

# Ingestion is now using a separate Redis cluster for better resource isolation.
# Django and plugin-server currently communicate via the reload-plugins Redis
# pubsub channel, pushed to when plugin configs change.
# We should move away to a different communication channel and remove this.
PLUGINS_RELOAD_REDIS_URL = os.getenv("PLUGINS_RELOAD_REDIS_URL", REDIS_URL)

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        # the django redis default client can be replica aware
        # if location is an array then the first element is the primary
        # and the rest are replicas
        "LOCATION": REDIS_URL if not REDIS_READER_URL else [REDIS_URL, REDIS_READER_URL],
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "COMPRESSOR": "posthog.caching.tolerant_zlib_compressor.TolerantZlibCompressor",
        },
        "KEY_PREFIX": "posthog",
    }
}

if TEST:
    CACHES["default"] = {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
