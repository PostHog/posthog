import os

from posthog.settings.utils import get_from_env, get_list, str_to_bool

TEMPORAL_NAMESPACE: str = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE: str = os.getenv("TEMPORAL_TASK_QUEUE", "general-purpose-task-queue")
TEMPORAL_HOST: str = os.getenv("TEMPORAL_HOST", "127.0.0.1")
TEMPORAL_PORT: str = os.getenv("TEMPORAL_PORT", "7233")
TEMPORAL_CLIENT_ROOT_CA: str | None = os.getenv("TEMPORAL_CLIENT_ROOT_CA", None)
TEMPORAL_CLIENT_CERT: str | None = os.getenv("TEMPORAL_CLIENT_CERT", None)
TEMPORAL_CLIENT_KEY: str | None = os.getenv("TEMPORAL_CLIENT_KEY", None)
TEMPORAL_WORKFLOW_MAX_ATTEMPTS: str = os.getenv("TEMPORAL_WORKFLOW_MAX_ATTEMPTS", "3")
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS: int | None = get_from_env(
    "GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", None, optional=True, type_cast=int
)
MAX_CONCURRENT_WORKFLOW_TASKS: int | None = get_from_env(
    "MAX_CONCURRENT_WORKFLOW_TASKS", None, optional=True, type_cast=int
)
MAX_CONCURRENT_ACTIVITIES: int | None = get_from_env("MAX_CONCURRENT_ACTIVITIES", None, optional=True, type_cast=int)

TEMPORAL_USE_EXTERNAL_LOGGER: bool = get_from_env("TEMPORAL_USE_EXTERNAL_LOGGER", False, type_cast=str_to_bool)
TEMPORAL_LOG_LEVEL: str = os.getenv("TEMPORAL_LOG_LEVEL", "INFO")
TEMPORAL_EXTERNAL_LOGS_QUEUE_SIZE: int = get_from_env("TEMPORAL_EXTERNAL_LOGS_QUEUE_SIZE", 100, type_cast=int)

BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 50  # 50MB
BATCH_EXPORT_S3_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES: int = get_from_env(
    "BATCH_EXPORT_S3_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES", 0, type_cast=int
)
BATCH_EXPORT_S3_MAX_CONCURRENT_UPLOADS: int = get_from_env("BATCH_EXPORT_S3_MAX_CONCURRENT_UPLOADS", 5, type_cast=int)

BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 100  # 100MB
BATCH_EXPORT_SNOWFLAKE_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES: int = get_from_env(
    "BATCH_EXPORT_SNOWFLAKE_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES", 1024 * 1024 * 300, type_cast=int
)

BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 50  # 50MB
BATCH_EXPORT_POSTGRES_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES: int = get_from_env(
    "BATCH_EXPORT_POSTGRES_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES", 1024 * 1024 * 300, type_cast=int
)

BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 100  # 100MB
BATCH_EXPORT_BIGQUERY_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES: int = get_from_env(
    "BATCH_EXPORT_BIGQUERY_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES", 0, type_cast=int
)

BATCH_EXPORT_REDSHIFT_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 8  # 8MB
BATCH_EXPORT_REDSHIFT_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES: int = get_from_env(
    "BATCH_EXPORT_REDSHIFT_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES", 1024 * 1024 * 300, type_cast=int
)

BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES: int = get_from_env(
    "BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES", 1024 * 1024 * 50, type_cast=int
)
BATCH_EXPORT_HTTP_BATCH_SIZE: int = get_from_env("BATCH_EXPORT_HTTP_BATCH_SIZE", 5000, type_cast=int)

BATCH_EXPORT_BUFFER_QUEUE_MAX_SIZE_BYTES: int = 1024 * 1024 * 300  # 300MB

BATCH_EXPORT_HEARTBEAT_TIMEOUT_SECONDS: int = get_from_env("BATCH_EXPORT_HEARTBEAT_TIMEOUT_SECONDS", 30, type_cast=int)

BATCH_EXPORT_ORDERLESS_TEAM_IDS: list[str] = get_list(os.getenv("BATCH_EXPORT_ORDERLESS_TEAM_IDS", ""))
UNCONSTRAINED_TIMESTAMP_TEAM_IDS: list[str] = get_list(os.getenv("UNCONSTRAINED_TIMESTAMP_TEAM_IDS", ""))
DEFAULT_TIMESTAMP_LOOKBACK_DAYS = 7
# Comma separated list of overrides in the format "team_id:lookback_days"
OVERRIDE_TIMESTAMP_TEAM_IDS: dict[int, int] = dict(
    [map(int, o.split(":")) for o in os.getenv("OVERRIDE_TIMESTAMP_TEAM_IDS", "").split(",") if o]  # type: ignore
)

CLICKHOUSE_MAX_EXECUTION_TIME: int = get_from_env("CLICKHOUSE_MAX_EXECUTION_TIME", 0, type_cast=int)
CLICKHOUSE_MAX_MEMORY_USAGE: int = get_from_env(
    "CLICKHOUSE_MAX_MEMORY_USAGE", 150 * 1000 * 1000 * 1000, type_cast=int
)  # 150GB
CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT: int = get_from_env("CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT", 10000, type_cast=int)
# Comma separated list of overrides in the format "team_id:block_size"
CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES: dict[int, int] = dict(
    [map(int, o.split(":")) for o in os.getenv("CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES", "").split(",") if o]  # type: ignore
)
CLICKHOUSE_OFFLINE_5MIN_CLUSTER_HOST: str | None = os.getenv("CLICKHOUSE_OFFLINE_5MIN_CLUSTER_HOST", None)

# The teams that will use the internal stage for batch exports (for destinations that support it)
BATCH_EXPORT_USE_INTERNAL_S3_STAGE_TEAM_IDS: list[str] = get_list(
    os.getenv("BATCH_EXPORT_USE_INTERNAL_S3_STAGE_TEAM_IDS", "")
)
BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT: str = os.getenv(
    "BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT", "http://objectstorage:19000"
)
BATCH_EXPORT_OBJECT_STORAGE_REGION: str = os.getenv("BATCH_EXPORT_OBJECT_STORAGE_REGION", "us-east-1")
BATCH_EXPORT_INTERNAL_STAGING_BUCKET: str = os.getenv("BATCH_EXPORT_INTERNAL_STAGING_BUCKET", "posthog")
# The number of partitions controls how many files ClickHouse writes to concurrently
BATCH_EXPORT_CLICKHOUSE_S3_PARTITIONS: int = get_from_env("BATCH_EXPORT_CLICKHOUSE_S3_PARTITIONS", 5, type_cast=int)
BATCH_EXPORT_TRANSFORMER_MAX_WORKERS: int = get_from_env("BATCH_EXPORT_TRANSFORMER_MAX_WORKERS", 2, type_cast=int)
