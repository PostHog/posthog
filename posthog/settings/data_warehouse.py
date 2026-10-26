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

# Default (connect, read) timeout in seconds for an HTTP request that an import source sends with no
# timeout of its own. The read value is the longest silence between two socket reads, not a limit on
# the whole response. A source that needs more passes its own timeout, which always wins.
DATA_WAREHOUSE_SOURCE_CONNECT_TIMEOUT_SECONDS = get_from_env(
    "DATA_WAREHOUSE_SOURCE_CONNECT_TIMEOUT_SECONDS", 30.0, type_cast=float
)
DATA_WAREHOUSE_SOURCE_READ_TIMEOUT_SECONDS = get_from_env(
    "DATA_WAREHOUSE_SOURCE_READ_TIMEOUT_SECONDS", 300.0, type_cast=float
)

# Longest time in seconds that one source request may take, from the start of its first try to the
# end of its last, with all retries and waits. Each try gets only the time that is left, so a stalled
# vendor holds a worker for this long at most. Keep it at or below
# DATA_WAREHOUSE_IMPORT_PREEMPTION_QUIET_PERIOD_SECONDS, the time a source gets to hand off at a worker
# shutdown. A client can pass its own value when a vendor's rate limit window is longer.
DATA_WAREHOUSE_SOURCE_RETRY_BUDGET_SECONDS = get_from_env(
    "DATA_WAREHOUSE_SOURCE_RETRY_BUDGET_SECONDS", 300.0, type_cast=float
)

# Longest server-provided retry delay (`Retry-After` or a rate limit reset header) in seconds that
# the shared REST client and the request pacer wait for. The REST client fails the request with a
# retryable error when the server asks for more, and the pacer holds for this long at most.
DATA_WAREHOUSE_SOURCE_MAX_RETRY_AFTER_SECONDS = get_from_env(
    "DATA_WAREHOUSE_SOURCE_MAX_RETRY_AFTER_SECONDS", 300.0, type_cast=float
)

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

# The size-driven split budget for tables that upsert on a primary key (incremental, webhook, xmin).
# Those upserts go through deltalite, whose peak memory does not grow with partition size, while on an
# md5 table every extra partition adds one more rewritten file to each merge. The delta-rs MERGE runs on
# such a table only for a batch that deltalite fails, and this larger cap bounds partition size for that
# fallback. The OOM-history trigger still splits a table whose fallback runs out of memory.
# A value below DATA_WAREHOUSE_TARGET_PARTITION_BYTES has no effect.
DATA_WAREHOUSE_MERGE_TARGET_PARTITION_BYTES = get_from_env(
    "DATA_WAREHOUSE_MERGE_TARGET_PARTITION_BYTES", 2_000_000_000, type_cast=int
)

# Coarsening of md5 tables that upsert on a primary key. Such an upsert rewrites at least one file in
# every md5 partition, so the partition count, not the partition size, sets the merge cost. For these
# tables the coarsening path uses the merge budget above, and picks the divisor of the current count
# nearest to TARGET, never below MIN. MIN is the memory governor's cap on the partitions that one upsert
# merges in parallel, so a coarser table keeps all of its merge parallelism. TARGET is twice that cap,
# so the parallel partition tasks still share the work when one partition is slow.
# The automatic path uses this policy only when the `data-warehouse-merge-auto-coarsen` feature flag is on
# for the schema. Otherwise it coarsens these tables on the base budget as for any other table.
# A `stage_warehouse_coarsening` nomination always uses this policy.
DATA_WAREHOUSE_MERGE_MD5_PARTITION_TARGET = get_from_env("DATA_WAREHOUSE_MERGE_MD5_PARTITION_TARGET", 8, type_cast=int)
DATA_WAREHOUSE_MERGE_MD5_PARTITION_MIN = get_from_env("DATA_WAREHOUSE_MERGE_MD5_PARTITION_MIN", 4, type_cast=int)

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
# A lite vacuum also runs once this many hours have passed since the last vacuum, whatever the commit
# count. A checkpoint drops tombstones older than delta's 7-day `deletedFileRetentionDuration`, and a lite
# vacuum cannot find a dead file without its tombstone. This interval plus the 24-hour vacuum retention
# must stay below 7 days, so a table that commits slowly does not leak its dead files.
DATA_WAREHOUSE_VACUUM_MAX_INTERVAL_HOURS = get_from_env("DATA_WAREHOUSE_VACUUM_MAX_INTERVAL_HOURS", 120, type_cast=int)
# A full vacuum lists the whole table and deletes the files that the log does not name, with the same
# 24-hour retention. It collects the files that a lite vacuum never finds: files that a crashed writer
# left, and files whose tombstone a checkpoint dropped.
DATA_WAREHOUSE_FULL_VACUUM_INTERVAL_HOURS = get_from_env(
    "DATA_WAREHOUSE_FULL_VACUUM_INTERVAL_HOURS", 168, type_cast=int
)
# Compact Delta tables with deltalite's native `DeltaLiteTable.compact` instead of delta-rs
# `optimize.compact`. deltalite streams each bin under the load slot's memory budget. A deltalite build
# without `compact`, a table that deltalite refuses, or a deltalite failure falls back to delta-rs.
DATA_WAREHOUSE_DELTALITE_COMPACTION = get_from_env("DATA_WAREHOUSE_DELTALITE_COMPACTION", False, type_cast=str_to_bool)
# Row-group cap for the files deltalite writes. A merge upsert closes a row group at this many encoded
# bytes, and a deltalite compaction closes one at this many decoded bytes, so compaction does not join
# the row groups again. A reader fetches one whole row group before it decodes it, so smaller row groups
# lower upsert and query memory on tables with wide rows. 0 turns the cap off and keeps deltalite's
# defaults.
DATA_WAREHOUSE_DELTALITE_MAX_ROW_GROUP_BYTES = get_from_env(
    "DATA_WAREHOUSE_DELTALITE_MAX_ROW_GROUP_BYTES", 16 * 1024 * 1024, type_cast=int
)
# Size each deltalite reader by the largest row group of its file instead of by the whole file. The
# writer reads the footers of the candidate files only when the whole-file sizes keep the governor's plan
# narrow. A footer that cannot be read keeps the whole-file size. False turns the footer reads off.
DATA_WAREHOUSE_DELTALITE_GOVERNOR_ROW_GROUP_SIZING = get_from_env(
    "DATA_WAREHOUSE_DELTALITE_GOVERNOR_ROW_GROUP_SIZING", True, type_cast=str_to_bool
)
# Lets a deltalite upsert whose slice-sized plan is narrower than the widest plan borrow idle pod memory,
# up to DATA_WAREHOUSE_DELTALITE_GOVERNOR_BORROW_MAX_SLICES slices, and run more partition workers and
# readers. A borrow takes at most half of the free pod memory and never happens while an upsert waits for
# room. "advisory" logs the borrowed plan and keeps the slice-sized plan. "enforce" runs the borrowed plan,
# and needs DELTALITE_GOVERNOR_MODE=enforce. "off" computes nothing.
DATA_WAREHOUSE_DELTALITE_GOVERNOR_BORROW = get_from_env("DATA_WAREHOUSE_DELTALITE_GOVERNOR_BORROW", "advisory")
DATA_WAREHOUSE_DELTALITE_GOVERNOR_BORROW_MAX_SLICES = get_from_env(
    "DATA_WAREHOUSE_DELTALITE_GOVERNOR_BORROW_MAX_SLICES", 4.0, type_cast=float
)
# deltalite keeps the primary keys of the data files that a merge reads or writes in a per-process cache,
# so a later merge into the same table decides most files without a read from object storage. The cache
# size comes from the DELTALITE_PROBE_CACHE_BYTES environment variable (default 128 MiB per process). False makes every merge read each
# candidate file again, and needs a deltalite build that has the probe cache.
DATA_WAREHOUSE_DELTALITE_PROBE_CACHE = get_from_env("DATA_WAREHOUSE_DELTALITE_PROBE_CACHE", True, type_cast=str_to_bool)
# A rebuild run (first sync, reset, full refresh) compacts its own files once a compaction would remove
# this many, so a long rebuild does not leave one post-load pass that outlasts the stuck-batch timeout.
DATA_WAREHOUSE_REBUILD_COMPACT_MIN_REMOVABLE_FILES = get_from_env(
    "DATA_WAREHOUSE_REBUILD_COMPACT_MIN_REMOVABLE_FILES", 20_000, type_cast=int
)

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

# Only a local setup has a Redis on localhost. In a deployed environment nothing listens there,
# so an environment that sets neither of these turned every warehouse Redis call into a connection
# error. Leave the host unset instead, which lets the callers fall back to the shared REDIS_URL or
# say that the feature is not configured.
_DEFAULT_DATA_WAREHOUSE_REDIS_HOST = "localhost" if DEBUG or TEST else None
DATA_WAREHOUSE_REDIS_HOST: str | None = os.getenv(
    "DATA_WAREHOUSE_REDIS_HOST", os.getenv("POSTHOG_REDIS_HOST", _DEFAULT_DATA_WAREHOUSE_REDIS_HOST)
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

# Bounds on a set of queued batches the V3 loader writes to a Delta table as one commit. The loader
# holds the whole set decoded in Arrow, then copies it once more while it deduplicates and partitions,
# so a set must stay inside the memory slice the deltalite governor sizes per concurrent upsert
# (memory_governor.py): with a 29 GiB pod, 16 groups in flight and a 2 GiB reserve, that slice is
# about 1.3 GiB, of which 750 MiB goes to four partition workers. The row cap equals one extraction
# chunk, the largest single batch the loader already takes. The count cap is only a backstop.
# When each batch records its decoded Arrow size and the pod limit is known, the copies of a set the
# loader holds may use SLOT_SHARE of that slice, and the set's Arrow size never exceeds
# MAX_ARROW_BYTES. Otherwise MAX_BYTES caps the parquet on disk, which decodes to Arrow several
# times its size.
DATA_WAREHOUSE_V3_COALESCE_MAX_BATCHES = get_from_env("DATA_WAREHOUSE_V3_COALESCE_MAX_BATCHES", 128, type_cast=int)
DATA_WAREHOUSE_V3_COALESCE_MAX_ROWS = get_from_env("DATA_WAREHOUSE_V3_COALESCE_MAX_ROWS", 500_000, type_cast=int)
DATA_WAREHOUSE_V3_COALESCE_MAX_BYTES = get_from_env(
    "DATA_WAREHOUSE_V3_COALESCE_MAX_BYTES", 64 * 1024 * 1024, type_cast=int
)
DATA_WAREHOUSE_V3_COALESCE_SLOT_SHARE = get_from_env("DATA_WAREHOUSE_V3_COALESCE_SLOT_SHARE", 0.4, type_cast=float)
DATA_WAREHOUSE_V3_COALESCE_MAX_ARROW_BYTES = get_from_env(
    "DATA_WAREHOUSE_V3_COALESCE_MAX_ARROW_BYTES", 512 * 1024 * 1024, type_cast=int
)

# Consecutive configuration errors (bad credentials, unknown database, unreachable host) after which
# PostHog pauses a destination instead of letting every scheduled run fail against it.
DATA_WAREHOUSE_DESTINATION_PAUSE_AFTER_CONFIGURATION_FAILURES = get_from_env(
    "DATA_WAREHOUSE_DESTINATION_PAUSE_AFTER_CONFIGURATION_FAILURES", 3, type_cast=int
)
