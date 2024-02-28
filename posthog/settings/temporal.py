import os
from typing import Dict

from posthog.settings.utils import get_list, get_from_env

TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "no-sandbox-python-django")
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "127.0.0.1")
TEMPORAL_PORT = os.getenv("TEMPORAL_PORT", "7233")
TEMPORAL_CLIENT_ROOT_CA = os.getenv("TEMPORAL_CLIENT_ROOT_CA", None)
TEMPORAL_CLIENT_CERT = os.getenv("TEMPORAL_CLIENT_CERT", None)
TEMPORAL_CLIENT_KEY = os.getenv("TEMPORAL_CLIENT_KEY", None)
TEMPORAL_WORKFLOW_MAX_ATTEMPTS = os.getenv("TEMPORAL_WORKFLOW_MAX_ATTEMPTS", "3")

BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024 * 50  # 50MB
BATCH_EXPORT_SNOWFLAKE_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024 * 100  # 100MB
BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024 * 50  # 50MB
BATCH_EXPORT_BIGQUERY_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024 * 100  # 100MB
BATCH_EXPORT_HTTP_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024 * 10  # 10MB
BATCH_EXPORT_HTTP_BATCH_SIZE = 1000

UNCONSTRAINED_TIMESTAMP_TEAM_IDS = get_list(os.getenv("UNCONSTRAINED_TIMESTAMP_TEAM_IDS", ""))

CLICKHOUSE_MAX_EXECUTION_TIME = get_from_env("CLICKHOUSE_MAX_EXECUTION_TIME", 0, type_cast=int)
CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT = get_from_env("CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT", 10000, type_cast=int)
# Comma separated list of overrides in the format "team_id:block_size"
CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES: Dict[int, int] = dict(
    [map(int, o.split(":")) for o in os.getenv("CLICKHOUSE_MAX_BLOCK_SIZE_OVERRIDES", "").split(",") if o]  # type: ignore
)
