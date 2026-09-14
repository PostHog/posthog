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

# The computed "am I a local dev setup?" signal. General dev-mode checks (is_dev_mode() and
# friends: DuckLake shadow execution, MCP localhost scopes, dev middleware) must read THIS,
# not the env-overridable value below — the override is meant to redirect warehouse storage
# only, not to flip every dev-mode behavior in a production-mode deployment.
USE_LOCAL_SETUP_DEFAULT = TEST or (
    DEBUG and len(os.getenv("OBJECT_STORAGE_ENDPOINT", "http://objectstorage:19000")) > 0
)

# Every warehouse STORAGE path branches on this: delta write creds, HogQL S3 read creds,
# saved-query url_pattern. Self-hosted-style stacks that run DEBUG=0 against an in-stack
# S3-compatible store (MinIO in the compose stacks) can set USE_LOCAL_SETUP=1 to force the
# local path, otherwise they reach for real AWS creds. Boolean via str_to_bool ("1"/"true"),
# and it must be set on every Django process (web and workers) so the write and read sides
# agree on where the data lives.
USE_LOCAL_SETUP = get_from_env("USE_LOCAL_SETUP", USE_LOCAL_SETUP_DEFAULT, type_cast=str_to_bool)

PYARROW_DEBUG_LOGGING = get_from_env("PYARROW_DEBUG_LOGGING", False, type_cast=str_to_bool)

# Load the full warehouse source catalog (every vendor SDK) at web-worker startup, before
# the worker starts serving, so its first warehouse query doesn't pay the multi-second
# catalog import at request time. WSGI workers load while importing posthog.wsgi, ASGI
# workers during lifespan startup; a failed prewarm logs and leaves the worker to lazy
# loading. Off by default everywhere, including the shared web launcher: deployment
# config enables it only for the dedicated Granian deployment that serves warehouse
# queries, so web and report workers, shells, migrations, tests, and Celery keep lazy
# source loading.
PREWARM_WAREHOUSE_SOURCE_REGISTRY = get_from_env("PREWARM_WAREHOUSE_SOURCE_REGISTRY", False, type_cast=str_to_bool)

# Region hosting BUCKET_URL. Only used to build the bucket's virtual-hosted hostname for the
# egress-proxy bypass in products/data_warehouse/backend/s3_proxy.py; the AWS clients resolve their
# own region as before. Falls back to the ambient AWS_REGION, and an empty value leaves the bypass
# off (the bypass itself is gated by a feature flag, not by a setting).
DATA_WAREHOUSE_S3_REGION: str = os.getenv("DATA_WAREHOUSE_S3_REGION", os.getenv("AWS_REGION", ""))

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

# How often each sync activity self-reports its workload (phase, buffer bytes, RSS) to the warehouse
# Redis, for post-mortem enrichment of silent worker deaths. Zero or negative disables reporting
# entirely (the fleet kill switch — hooks become no-ops and no thread starts).
DATA_WAREHOUSE_WORKLOAD_REPORT_INTERVAL_SECONDS = get_from_env(
    "DATA_WAREHOUSE_WORKLOAD_REPORT_INTERVAL_SECONDS", 30.0, type_cast=float
)

# A run whose peak self-reported buffer crosses this emits one `dwh_workload_high_watermark` event on
# completion. Deaths are enriched separately; this captures the tail of *surviving* runs, which is
# what calibrates OOM-classification thresholds. Zero disables the event.
DATA_WAREHOUSE_WORKLOAD_HIGH_WATERMARK_BYTES = get_from_env(
    "DATA_WAREHOUSE_WORKLOAD_HIGH_WATERMARK_BYTES", 500_000_000, type_cast=int
)

# A schema that records at least this many sync OOMs within the lookback window is force-repartitioned
# even when its largest partition is within the size budget — its real merge working set is bigger than
# the compressed at-rest size implies (e.g. wide nested-JSON columns). See ExternalDataSchemaOOMEvent.
DATA_WAREHOUSE_REPARTITION_OOM_THRESHOLD = get_from_env("DATA_WAREHOUSE_REPARTITION_OOM_THRESHOLD", 3, type_cast=int)
DATA_WAREHOUSE_REPARTITION_OOM_WINDOW_DAYS = get_from_env(
    "DATA_WAREHOUSE_REPARTITION_OOM_WINDOW_DAYS", 7, type_cast=int
)

# Classification of a suspected OOM (see ExternalDataSchemaOOMEvent). Infrastructure takes
# down many unrelated schemas at once, so an occurrence sharing a window with at least this many
# distinct schemas across the fleet is attributed to infrastructure rather than to any one table.
# The window extends this far on EACH SIDE of the occurrence being judged (total span = 2x).
DATA_WAREHOUSE_OOM_INFRA_BURST_WINDOW_SECONDS = get_from_env(
    "DATA_WAREHOUSE_OOM_INFRA_BURST_WINDOW_SECONDS", 1800, type_cast=int
)
DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_SCHEMAS = get_from_env(
    "DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_SCHEMAS", 50, type_cast=int
)
# A burst must also span this many distinct teams: one tenant's source outage kills all of that
# tenant's schemas at once, which is not infrastructure and must not suppress other tenants' counting.
DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_TEAMS = get_from_env("DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_TEAMS", 10, type_cast=int)

# A merge-phase death whose own peak buffer crossed this blocks coarsening whatever the classification
# rules concluded, because enlarging the merge of a table last seen holding real memory is not a safe
# bet to make on a plausible exclusion.
DATA_WAREHOUSE_COARSEN_BLOCK_MERGE_PEAK_BYTES = get_from_env(
    "DATA_WAREHOUSE_COARSEN_BLOCK_MERGE_PEAK_BYTES", 1_048_576, type_cast=int
)

# Pre-write vacuum runs when this many delta commits have accrued since the last vacuum. Decoupled from
# merge success so tables that OOM their merge still get their tombstones cleared (the compact-after-merge
# path never runs for them). Vacuum only deletes dead files, so it's memory-safe even on oversized tables.
DATA_WAREHOUSE_VACUUM_COMMIT_THRESHOLD = get_from_env("DATA_WAREHOUSE_VACUUM_COMMIT_THRESHOLD", 100, type_cast=int)

# delta-rs merge spill-to-disk. A merge decompresses the target partition into an Arrow working set that
# can exceed the 29 GB pod limit and OOM — killing every co-tenant activity on the pod. When set, delta-rs
# hands DataFusion a bounded memory pool: once the merge's in-memory bytes cross MAX_SPILL_SIZE it spills
# the overflow to its temp directory (the process TMPDIR) instead of allocating unbounded. Left as None,
# DataFusion runs with its unbounded default (today's behavior) — so this is a no-op until BOTH the byte
# budget and a scratch disk are provisioned (the temporal-worker-data-warehouse / warehouse-sources-load
# pods mount an ephemeral volume at /tmp and set these env vars).
#
# Sizing interacts with concurrency: each merge gets its own DataFusion pool, so N concurrent merges on a
# pod can hold up to N * MAX_SPILL_SIZE in memory and N * MAX_TEMP_DIRECTORY_SIZE on the shared disk. Keep
# MAX_SPILL_SIZE below the designed per-partition working set (~10 GB) so genuinely-large merges spill
# before the multi-tenant OOM, while typical small merges stay in memory (spilling is slow). Keep
# MAX_TEMP_DIRECTORY_SIZE small enough that a few concurrent spills fit the mounted disk.
DATA_WAREHOUSE_DELTA_MERGE_MAX_SPILL_SIZE_BYTES: int | None = get_from_env(
    "DATA_WAREHOUSE_DELTA_MERGE_MAX_SPILL_SIZE_BYTES", None, optional=True, type_cast=int
)
DATA_WAREHOUSE_DELTA_MERGE_MAX_TEMP_DIRECTORY_SIZE_BYTES: int | None = get_from_env(
    "DATA_WAREHOUSE_DELTA_MERGE_MAX_TEMP_DIRECTORY_SIZE_BYTES", None, optional=True, type_cast=int
)

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
