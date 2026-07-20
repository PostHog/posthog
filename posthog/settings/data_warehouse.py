import os

from posthog.settings import TEST
from posthog.settings.base_variables import DEBUG
from posthog.settings.data_stores import DATABASE_URL, PRODUCT_DB_WRITER_URLS
from posthog.settings.utils import get_from_env, str_to_bool

DATAWAREHOUSE_LOCAL_BUCKET_REGION = os.getenv("DATAWAREHOUSE_LOCAL_BUCKET_REGION", "us-east-1")
DATAWAREHOUSE_LOCAL_ACCESS_KEY = os.getenv("DATAWAREHOUSE_LOCAL_ACCESS_KEY", "object_storage_root_user")
DATAWAREHOUSE_LOCAL_ACCESS_SECRET = os.getenv("DATAWAREHOUSE_LOCAL_ACCESS_SECRET", "object_storage_root_password")
DATAWAREHOUSE_BUCKET_DOMAIN = os.getenv("DATAWAREHOUSE_BUCKET_DOMAIN", "objectstorage:19000")


DATAWAREHOUSE_BUCKET = os.getenv("DATAWAREHOUSE_BUCKET", "data-warehouse")
BUCKET_URL = os.getenv("BUCKET_URL", "s3://data-warehouse")
BUCKET_PATH = os.getenv("BUCKET_PATH", "data-warehouse")

USE_LOCAL_SETUP = TEST or (DEBUG and len(os.getenv("OBJECT_STORAGE_ENDPOINT", "http://objectstorage:19000")) > 0)

PYARROW_DEBUG_LOGGING = get_from_env("PYARROW_DEBUG_LOGGING", False, type_cast=str_to_bool)

# Rollback-only escape hatch: restores the legacy delta-rs unsafe-rename S3 backend,
# which has no commit-conflict detection. Default (false) keeps conditional-put commits.
DATA_WAREHOUSE_DELTA_S3_ALLOW_UNSAFE_RENAME = get_from_env(
    "DATA_WAREHOUSE_DELTA_S3_ALLOW_UNSAFE_RENAME", False, type_cast=str_to_bool
)

# At-rest (compressed) byte budget per Delta partition. The auto-repartition controller rewrites a
# table into a finer scheme once its largest partition exceeds this. delta-rs merges decompress the
# whole target partition into an Arrow working set — roughly ~20x the at-rest size, and far more for
# wide nested-JSON columns. Worker pods are multi-tenant (a single OOM kills every co-tenant activity),
# so the budget must leave headroom for concurrent merges under the 29 GB pod limit, not just fit one.
# ~0.5 GB → ~10 GB worst-case working set, leaving room for other activities on the same pod.
# The wide-column case (where the ~20x multiplier under-counts) is caught empirically by the OOM-history
# override below rather than by trying to model per-column expansion here.
DATA_WAREHOUSE_TARGET_PARTITION_BYTES = get_from_env(
    "DATA_WAREHOUSE_TARGET_PARTITION_BYTES", 500_000_000, type_cast=int
)

# A schema that records at least this many sync OOMs within the lookback window is force-repartitioned
# even when its largest partition is within the size budget — its real merge working set is bigger than
# the compressed at-rest size implies (e.g. wide nested-JSON columns). See ExternalDataSchemaOOMEvent.
DATA_WAREHOUSE_REPARTITION_OOM_THRESHOLD = get_from_env("DATA_WAREHOUSE_REPARTITION_OOM_THRESHOLD", 3, type_cast=int)
DATA_WAREHOUSE_REPARTITION_OOM_WINDOW_DAYS = get_from_env(
    "DATA_WAREHOUSE_REPARTITION_OOM_WINDOW_DAYS", 7, type_cast=int
)

# Pre-write vacuum runs when this many delta commits have accrued since the last vacuum. Decoupled from
# merge success so tables that OOM their merge still get their tombstones cleared (the compact-after-merge
# path never runs for them). Vacuum only deletes dead files, so it's memory-safe even on oversized tables.
DATA_WAREHOUSE_VACUUM_COMMIT_THRESHOLD = get_from_env("DATA_WAREHOUSE_VACUUM_COMMIT_THRESHOLD", 100, type_cast=int)

GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL: str | None = os.getenv("GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL")
GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY: str | None = os.getenv("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY")
GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID: str | None = os.getenv("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID")
GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI: str | None = os.getenv("GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI")

GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL: str | None = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL")
GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY: str | None = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY")
GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY_ID: str | None = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY_ID")
GOOGLE_SHEETS_SERVICE_ACCOUNT_TOKEN_URI: str | None = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_TOKEN_URI")

DATA_WAREHOUSE_REDIS_HOST: str | None = os.getenv(
    "DATA_WAREHOUSE_REDIS_HOST", os.getenv("POSTHOG_REDIS_HOST", "localhost")
)
DATA_WAREHOUSE_REDIS_PORT: str | None = os.getenv("DATA_WAREHOUSE_REDIS_PORT", os.getenv("POSTHOG_REDIS_PORT", "6379"))

CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST: str | None = os.getenv("CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST")
CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT: str | None = os.getenv("CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT")
CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE: str | None = os.getenv("CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE")
CLICKHOUSE_HOGQL_RDSPROXY_READ_USER: str | None = os.getenv("CLICKHOUSE_HOGQL_RDSPROXY_READ_USER")
CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD: str | None = os.getenv("CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD")

WAREHOUSE_SOURCES_DATABASE_URL: str = (
    os.getenv("WAREHOUSE_SOURCES_DATABASE_URL") or PRODUCT_DB_WRITER_URLS.get("warehouse_sources_queue") or DATABASE_URL
)

# Warehouse-pipeline and cyclotron Kafka config live in `posthog/settings/kafka.py`
# (profiles `warehouse_sources` and `cyclotron`) — read from `settings.KAFKA_PROFILES[...]`
# or via the back-compat top-level names that settings/kafka.py exposes.
