import os

from posthog.settings.utils import get_from_env, get_list

TEMPORAL_NAMESPACE: str = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE: str = os.getenv("TEMPORAL_TASK_QUEUE", "no-sandbox-python-django")
TEMPORAL_HOST: str = os.getenv("TEMPORAL_HOST", "127.0.0.1")
TEMPORAL_PORT: str = os.getenv("TEMPORAL_PORT", "7233")
TEMPORAL_CLIENT_ROOT_CA: str | None = os.getenv("TEMPORAL_CLIENT_ROOT_CA", None)
TEMPORAL_CLIENT_CERT: str | None = os.getenv("TEMPORAL_CLIENT_CERT", None)
TEMPORAL_CLIENT_KEY: str | None = os.getenv("TEMPORAL_CLIENT_KEY", None)
TEMPORAL_WORKFLOW_MAX_ATTEMPTS: str = os.getenv("TEMPORAL_WORKFLOW_MAX_ATTEMPTS", "3")

BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 50  # 50MB
BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 100  # 100MB
BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 50  # 50MB
BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 100  # 100MB
BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES: int = 1024 * 1024 * 50  # 50MB
BATCH_EXPORT_HTTP_BATCH_SIZE: int = 5000

UNCONSTRAINED_TIMESTAMP_TEAM_IDS: list[str] = get_list(os.getenv("UNCONSTRAINED_TIMESTAMP_TEAM_IDS", ""))
ASYNC_ARROW_STREAMING_TEAM_IDS: list[str] = get_list(os.getenv("ASYNC_ARROW_STREAMING_TEAM_IDS", ""))
DEFAULT_TIMESTAMP_LOOKBACK_DAYS = 7
# Comma separated list of overrides in the format "team_id:lookback_days"
OVERRIDE_TIMESTAMP_TEAM_IDS: dict[int, int] = dict(
    [map(int, o.split(":")) for o in os.getenv("OVERRIDE_TIMESTAMP_TEAM_IDS", "").split(",") if o]  # type: ignore
)

CLICKHOUSE_MAX_EXECUTION_TIME: int = get_from_env("CLICKHOUSE_MAX_EXECUTION_TIME", 0, type_cast=int)
CLICKHOUSE_MAX_MEMORY_USAGE: int = get_from_env("CLICKHOUSE_MAX_MEMORY_USAGE", 100 * 1000 * 1000 * 1000, type_cast=int)
CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT: int = get_from_env("CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT", 10000, type_cast=int)
# Comma separated list of overrides in the format "team_id:block_size"
CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES: dict[int, int] = dict(
    [map(int, o.split(":")) for o in os.getenv("CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES", "").split(",") if o]  # type: ignore
)
