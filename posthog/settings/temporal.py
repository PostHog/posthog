import os

from posthog.settings.utils import get_from_env

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

TEMPORAL_LOG_LEVEL: str = os.getenv("TEMPORAL_LOG_LEVEL", "INFO")
TEMPORAL_LOG_LEVEL_PRODUCE: str = os.getenv("TEMPORAL_LOG_LEVEL_PRODUCE", "DEBUG")
TEMPORAL_EXTERNAL_LOGS_QUEUE_SIZE: int = get_from_env("TEMPORAL_EXTERNAL_LOGS_QUEUE_SIZE", 0, type_cast=int)

CLICKHOUSE_MAX_EXECUTION_TIME: int = get_from_env("CLICKHOUSE_MAX_EXECUTION_TIME", 86400, type_cast=int)  # 1 day
CLICKHOUSE_MAX_MEMORY_USAGE: int = get_from_env(
    "CLICKHOUSE_MAX_MEMORY_USAGE", 150 * 1000 * 1000 * 1000, type_cast=int
)  # 150GB
CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT: int = get_from_env("CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT", 10000, type_cast=int)
# Comma separated list of overrides in the format "team_id:block_size"
CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES: dict[int, int] = dict(
    [map(int, o.split(":")) for o in os.getenv("CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES", "").split(",") if o]  # type: ignore
)
