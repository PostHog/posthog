import json
import os
from contextlib import suppress
from typing import Optional
from urllib.parse import urlparse

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from posthog.settings.base_variables import (
    DEBUG,
    IN_EVAL_TESTING,
    IS_COLLECT_STATIC,
    TEST,
)
from posthog.settings.utils import get_from_env, get_list, str_to_bool

# See https://docs.djangoproject.com/en/3.2/ref/settings/#std:setting-DATABASE-DISABLE_SERVER_SIDE_CURSORS
DISABLE_SERVER_SIDE_CURSORS: bool = get_from_env("USING_PGBOUNCER", False, type_cast=str_to_bool)
# See https://docs.djangoproject.com/en/3.2/ref/settings/#std:setting-DATABASE-DISABLE_SERVER_SIDE_CURSORS
DEFAULT_AUTO_FIELD: str = "django.db.models.AutoField"

# Configuration for sqlcommenter
SQLCOMMENTER_WITH_FRAMEWORK: bool = False


# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases


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
    PG_HOST: str = os.getenv("PGHOST", "localhost")
    PG_USER: str = os.getenv("PGUSER", "posthog")
    PG_PASSWORD: str = os.getenv("PGPASSWORD", "posthog")
    PG_PORT: str = os.getenv("PGPORT", "5432")
    PG_DATABASE: str = os.getenv(
        "PGDATABASE",
        # AI evals get their own database, as they fully reuse the DB between runs and only reset once per day, for perf
        "posthog_ai_eval" if IN_EVAL_TESTING else "posthog",
    )
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"postgres://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}",
    )
else:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

if DATABASE_URL:
    DATABASES: dict[str, dict] = {"default": dj_database_url.config(default=DATABASE_URL, conn_max_age=0)}

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

DATABASE_ROUTERS: list[str] = []

# Configure the database which will be used as a read replica.
# This should have all the same config as our main writer DB, just use a different host.
# Our database router will point here.
read_host = os.getenv("POSTHOG_POSTGRES_READ_HOST")
if read_host:
    DATABASES["replica"] = postgres_config(read_host)
    DATABASE_ROUTERS.append("posthog.dbrouter.ReplicaRouter")

# Add the persons_db_writer database configuration using PERSONS_DB_WRITER_URL
if os.getenv("PERSONS_DB_WRITER_URL"):
    DATABASES["persons_db_writer"] = dj_database_url.config(default=os.getenv("PERSONS_DB_WRITER_URL"), conn_max_age=0)

    # Fall back to the writer URL if no reader URL is set
    persons_reader_url = os.getenv("PERSONS_DB_READER_URL") or os.getenv("PERSONS_DB_WRITER_URL")
    DATABASES["persons_db_reader"] = dj_database_url.config(default=persons_reader_url, conn_max_age=0)
    if DISABLE_SERVER_SIDE_CURSORS:
        DATABASES["persons_db_writer"]["DISABLE_SERVER_SIDE_CURSORS"] = True
        DATABASES["persons_db_reader"]["DISABLE_SERVER_SIDE_CURSORS"] = True

    DATABASE_ROUTERS.insert(0, "posthog.person_db_router.PersonDBRouter")

# Opt-in to using the read replica
# Models using this will likely see better query latency, and better performance.
# Immediately reading after writing may not return consistent data if done in <100ms
# Pass in model classnames that should use the read replica

# Note: Regardless of settings, cursor usage will use the default DB unless otherwise specified.
# Database routers route models!
replica_opt_in = os.environ.get("READ_REPLICA_OPT_IN", "")
READ_REPLICA_OPT_IN: list[str] = get_list(replica_opt_in)

# Xdist Settings
# When running concurrent tests, PYTEST_XDIST_WORKER gets set to "gw0" ... "gwN"
# We use this setting to create multiple databases to achieve test isolation
PYTEST_XDIST_WORKER: str | None = os.getenv("PYTEST_XDIST_WORKER")
PYTEST_XDIST_WORKER_NUM: int | None = None
SUFFIX = ""
XDIST_SUFFIX = ""
try:
    if PYTEST_XDIST_WORKER is not None:
        XDIST_SUFFIX = f"_{PYTEST_XDIST_WORKER}"
        PYTEST_XDIST_WORKER_NUM = int("".join([x for x in PYTEST_XDIST_WORKER if x.isdigit()]))
except:
    pass

if IN_EVAL_TESTING:
    # AI evals get their own database, as they fully reuse the DB between runs and only reset once per day, for perf
    SUFFIX = "_ai_eval" + XDIST_SUFFIX
elif TEST:
    SUFFIX = "_test" + XDIST_SUFFIX

# Clickhouse Settings
CLICKHOUSE_TEST_DB: str = "posthog" + SUFFIX

CLICKHOUSE_HOST: str = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_OFFLINE_CLUSTER_HOST: str | None = os.getenv("CLICKHOUSE_OFFLINE_CLUSTER_HOST", None)
CLICKHOUSE_USER: str = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD: str = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE: str = CLICKHOUSE_TEST_DB if TEST else os.getenv("CLICKHOUSE_DATABASE", "default")
CLICKHOUSE_CLUSTER: str = os.getenv("CLICKHOUSE_CLUSTER", "posthog")
CLICKHOUSE_MIGRATIONS_CLUSTER: str = os.getenv("CLICKHOUSE_MIGRATIONS_CLUSTER", "posthog_migrations")
CLICKHOUSE_CA: str | None = os.getenv("CLICKHOUSE_CA", None)
CLICKHOUSE_SECURE: bool = get_from_env("CLICKHOUSE_SECURE", not TEST and not DEBUG, type_cast=str_to_bool)
CLICKHOUSE_VERIFY: bool = get_from_env("CLICKHOUSE_VERIFY", True, type_cast=str_to_bool)
CLICKHOUSE_ENABLE_STORAGE_POLICY: bool = get_from_env("CLICKHOUSE_ENABLE_STORAGE_POLICY", False, type_cast=str_to_bool)
CLICKHOUSE_SINGLE_SHARD_CLUSTER: str = os.getenv("CLICKHOUSE_SINGLE_SHARD_CLUSTER", "posthog_single_shard")
CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER = get_from_env(
    "CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER", default=False, type_cast=str_to_bool
)

CLICKHOUSE_USE_HTTP: str = get_from_env("CLICKHOUSE_USE_HTTP", False, type_cast=str_to_bool)
CLICKHOUSE_USE_HTTP_PER_TEAM = set[int]([])
with suppress(Exception):
    as_json = json.loads(os.getenv("CLICKHOUSE_USE_HTTP_PER_TEAM", "[]"))
    CLICKHOUSE_USE_HTTP_PER_TEAM = {int(v) for v in as_json}

QUERYSERVICE_HOST: str = get_from_env("QUERYSERVICE_HOST", CLICKHOUSE_HOST)
QUERYSERVICE_SECURE: bool = get_from_env("QUERYSERVICE_SECURE", CLICKHOUSE_SECURE, type_cast=str_to_bool)
QUERYSERVICE_VERIFY: bool = get_from_env("QUERYSERVICE_VERIFY", CLICKHOUSE_VERIFY, type_cast=str_to_bool)

CLICKHOUSE_CONN_POOL_MIN: int = get_from_env("CLICKHOUSE_CONN_POOL_MIN", 20, type_cast=int)
CLICKHOUSE_CONN_POOL_MAX: int = get_from_env("CLICKHOUSE_CONN_POOL_MAX", 1000, type_cast=int)

CLICKHOUSE_STABLE_HOST: str = get_from_env("CLICKHOUSE_STABLE_HOST", CLICKHOUSE_HOST)
# If enabled, some queries will use system.cluster table to query each shard
CLICKHOUSE_ALLOW_PER_SHARD_EXECUTION: bool = get_from_env(
    "CLICKHOUSE_ALLOW_PER_SHARD_EXECUTION", False, type_cast=str_to_bool
)

CLICKHOUSE_LOGS_CLUSTER_HOST: str = os.getenv("CLICKHOUSE_LOGS_CLUSTER_HOST", "localhost")
CLICKHOUSE_LOGS_CLUSTER_USER: str = os.getenv("CLICKHOUSE_LOGS_CLUSTER_USER", "default")
CLICKHOUSE_LOGS_CLUSTER_PASSWORD: str = os.getenv("CLICKHOUSE_LOGS_CLUSTER_PASSWORD", "")
CLICKHOUSE_LOGS_CLUSTER_DATABASE: str = CLICKHOUSE_TEST_DB if TEST else os.getenv("CLICKHOUSE_LOGS_DATABASE", "default")
CLICKHOUSE_LOGS_CLUSTER_SECURE: bool = get_from_env(
    "CLICKHOUSE_LOGS_CLUSTER_SECURE", not TEST and not DEBUG, type_cast=str_to_bool
)

# Per-team settings used for client/pool connection parameters. Note that this takes precedence over any workload-based
# routing. Keys should be strings, not numbers.
try:
    CLICKHOUSE_PER_TEAM_SETTINGS: dict = json.loads(os.getenv("CLICKHOUSE_PER_TEAM_SETTINGS", "{}"))
except Exception:
    CLICKHOUSE_PER_TEAM_SETTINGS = {}

# Per-team settings used for query execution. Keys should be strings, not numbers.
try:
    CLICKHOUSE_PER_TEAM_QUERY_SETTINGS: dict = json.loads(os.getenv("CLICKHOUSE_PER_TEAM_QUERY_SETTINGS", "{}"))
except Exception:
    CLICKHOUSE_PER_TEAM_QUERY_SETTINGS = {}

# Set of teams querying the data before we switched to new limits
API_QUERIES_LEGACY_TEAM_LIST: Optional[set[int]] = None
with suppress(Exception):
    as_json = json.loads(get_from_env("API_QUERIES_LEGACY_TEAM_LIST"))
    API_QUERIES_LEGACY_TEAM_LIST = {int(v) for v in as_json}

# Per-team API /query concurrent limits, e.g. {"2": 7}
API_QUERIES_PER_TEAM: dict[int, int] = {}
with suppress(Exception):
    as_json = json.loads(os.getenv("API_QUERIES_PER_TEAM", "{}"))
    API_QUERIES_PER_TEAM = {int(k): int(v) for k, v in as_json.items()}

API_QUERIES_ON_ONLINE_CLUSTER = set[int]([])
with suppress(Exception):
    as_json = json.loads(os.getenv("API_QUERIES_ON_ONLINE_CLUSTER", "[]"))
    API_QUERIES_ON_ONLINE_CLUSTER = {int(v) for v in as_json}

_clickhouse_http_protocol = "http://"
_clickhouse_http_port = "8123"
if CLICKHOUSE_SECURE:
    _clickhouse_http_protocol = "https://"
    _clickhouse_http_port = "8443"

CLICKHOUSE_HTTP_URL: str = f"{_clickhouse_http_protocol}{CLICKHOUSE_HOST}:{_clickhouse_http_port}/"

CLICKHOUSE_OFFLINE_HTTP_URL: str = (
    f"{_clickhouse_http_protocol}{CLICKHOUSE_OFFLINE_CLUSTER_HOST}:{_clickhouse_http_port}/"
)

if TEST or DEBUG or os.getenv("CLICKHOUSE_OFFLINE_CLUSTER_HOST", None) is None:
    # When testing, there is no offline cluster.
    # Also in EU, there is no offline cluster.
    CLICKHOUSE_OFFLINE_HTTP_URL = CLICKHOUSE_HTTP_URL

READONLY_CLICKHOUSE_USER: str | None = os.getenv("READONLY_CLICKHOUSE_USER", None)
READONLY_CLICKHOUSE_PASSWORD: str | None = os.getenv("READONLY_CLICKHOUSE_PASSWORD", None)


def _parse_kafka_hosts(hosts_string: str) -> list[str]:
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

# To support e.g. Multi-tenanted plans on Heroko, we support specifying a prefix for
# Kafka Topics. See
# https://devcenter.heroku.com/articles/multi-tenant-kafka-on-heroku#differences-to-dedicated-kafka-plans
# for details.
KAFKA_PREFIX = os.getenv("KAFKA_PREFIX", "")

KAFKA_BASE64_KEYS = get_from_env("KAFKA_BASE64_KEYS", False, type_cast=str_to_bool)

KAFKA_PRODUCER_SETTINGS = {
    key: value
    for key, value in {
        "client_id": get_from_env("KAFKA_PRODUCER_CLIENT_ID", optional=True),
        "metadata_max_age_ms": get_from_env("KAFKA_PRODUCER_METADATA_MAX_AGE_MS", optional=True, type_cast=int),
        "batch_size": get_from_env("KAFKA_PRODUCER_BATCH_SIZE", optional=True, type_cast=int),
        "max_request_size": get_from_env("KAFKA_PRODUCER_MAX_REQUEST_SIZE", optional=True, type_cast=int),
        "linger_ms": get_from_env("KAFKA_PRODUCER_LINGER_MS", optional=True, type_cast=int),
        "partitioner": get_from_env("KAFKA_PRODUCER_PARTITIONER", optional=True),
        "max_in_flight_requests_per_connection": get_from_env(
            "KAFKA_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION", optional=True, type_cast=int
        ),
    }.items()
    if value is not None
}

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

# A list of tokens for which events should be sent to the historical topic
# TODO: possibly remove this and replace with something that provides the
# separation of concerns between realtime and historical ingestion but without
# needing to have a deploy.
TOKENS_HISTORICAL_DATA = os.getenv("TOKENS_HISTORICAL_DATA", "").split(",")

# The last case happens when someone upgrades Heroku but doesn't have Redis installed yet. Collectstatic gets called before we can provision Redis.
if TEST or DEBUG or IS_COLLECT_STATIC:
    if PYTEST_XDIST_WORKER_NUM is not None:
        REDIS_URL = os.getenv("REDIS_URL", f"redis://localhost/{PYTEST_XDIST_WORKER_NUM}")
    else:
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
USE_REDIS_COMPRESSION = get_from_env("USE_REDIS_COMPRESSION", True, type_cast=str_to_bool)

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

CDP_API_URL = get_from_env("CDP_API_URL", "")

if not CDP_API_URL:
    CDP_API_URL = "http://localhost:6738" if DEBUG else "http://ingestion-cdp-api.posthog.svc.cluster.local"

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
