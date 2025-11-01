import os

from posthog.settings.base_variables import DEBUG
from posthog.settings.utils import get_from_env

TEMPORAL_NAMESPACE: str = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_HOST: str = os.getenv("TEMPORAL_HOST", "127.0.0.1")
TEMPORAL_PORT: str = os.getenv("TEMPORAL_PORT", "7233")
TEMPORAL_CLIENT_ROOT_CA: str | None = os.getenv("TEMPORAL_CLIENT_ROOT_CA", None)
TEMPORAL_CLIENT_CERT: str | None = os.getenv("TEMPORAL_CLIENT_CERT", None)
TEMPORAL_CLIENT_KEY: str | None = os.getenv("TEMPORAL_CLIENT_KEY", None)
TEMPORAL_WORKFLOW_MAX_ATTEMPTS: str = os.getenv("TEMPORAL_WORKFLOW_MAX_ATTEMPTS", "3")
TEMPORAL_USE_PYDANTIC_CONVERTER: bool = get_from_env("TEMPORAL_USE_PYDANTIC_CONVERTER", "0").lower() in [
    "1",
    "true",
    "t",
    "y",
    "yes",
]
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


# Temporal task queues
# Temporal has a limitation where a worker can only listen to a single queue.
# To avoid running multiple workers, when running locally (DEBUG=True), we use a single queue for all tasks.
# In production (DEBUG=False), we use separate queues for each worker type.
def _set_temporal_task_queue(task_queue: str) -> str:
    if DEBUG:
        return "development-task-queue"
    return task_queue


default_task_queue = os.getenv("TEMPORAL_TASK_QUEUE", "general-purpose-task-queue")
TEMPORAL_TASK_QUEUE: str = _set_temporal_task_queue(default_task_queue)
DATA_WAREHOUSE_TASK_QUEUE = _set_temporal_task_queue("data-warehouse-task-queue")
MAX_AI_TASK_QUEUE = _set_temporal_task_queue("max-ai-task-queue")
DATA_WAREHOUSE_COMPACTION_TASK_QUEUE = _set_temporal_task_queue("data-warehouse-compaction-task-queue")
BATCH_EXPORTS_TASK_QUEUE = _set_temporal_task_queue("batch-exports-task-queue")
DATA_MODELING_TASK_QUEUE = _set_temporal_task_queue("data-modeling-task-queue")
SYNC_BATCH_EXPORTS_TASK_QUEUE = _set_temporal_task_queue("no-sandbox-python-django")
GENERAL_PURPOSE_TASK_QUEUE = _set_temporal_task_queue("general-purpose-task-queue")
TASKS_TASK_QUEUE = _set_temporal_task_queue("tasks-task-queue")
TEST_TASK_QUEUE = _set_temporal_task_queue("test-task-queue")
BILLING_TASK_QUEUE = _set_temporal_task_queue("billing-task-queue")
VIDEO_EXPORT_TASK_QUEUE = _set_temporal_task_queue("video-export-task-queue")
MESSAGING_TASK_QUEUE = _set_temporal_task_queue("messaging-task-queue")
ANALYTICS_PLATFORM_TASK_QUEUE = _set_temporal_task_queue("analytics-platform-task-queue")
SESSION_REPLAY_TASK_QUEUE = _set_temporal_task_queue("session-replay-task-queue")
WEEKLY_DIGEST_TASK_QUEUE = _set_temporal_task_queue("weekly-digest-task-queue")
