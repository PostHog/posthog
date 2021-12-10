import os
from urllib.parse import urlparse

from posthog.constants import AnalyticsDBMS
from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import get_from_env, str_to_bool

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
