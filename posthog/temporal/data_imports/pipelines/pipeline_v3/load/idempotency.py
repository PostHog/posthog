from contextlib import contextmanager

from django.conf import settings

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

IDEMPOTENCY_KEY_PREFIX = "warehouse_pipelines:processed"
IDEMPOTENCY_TTL_SECONDS = (
    48 * 60 * 60
)  # 2 days (48 hours) -> should we keep it the same time we keep the messages in kafka?


@contextmanager
def _get_redis_client():
    """Get a Redis client for the data warehouse Redis instance."""
    redis_client = None
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for warehouse pipelines: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis_client = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        redis_client.ping()
    except Exception as e:
        capture_exception(e)

    try:
        yield redis_client
    finally:
        pass


def get_idempotency_key(team_id: str, schema_id: str, run_uuid: str, batch_index: int) -> str:
    """Generate a unique idempotency key for a batch."""
    return f"{IDEMPOTENCY_KEY_PREFIX}:{team_id}:{schema_id}:{run_uuid}:{batch_index}"


def is_batch_already_processed(team_id: str, schema_id: str, run_uuid: str, batch_index: int) -> bool:
    """Check if a batch has already been processed."""
    with _get_redis_client() as redis_client:
        if redis_client is None:
            return False  # TODO: should we raise an error here instead of reprocessing? -> maybe it makes sense to raise an error and then use deduplication logic on deltalake

        key = get_idempotency_key(team_id, schema_id, run_uuid, batch_index)
        return redis_client.exists(key) == 1


def mark_batch_as_processed(team_id: str, schema_id: str, run_uuid: str, batch_index: int) -> None:
    """Mark a batch as processed in the cache."""
    with _get_redis_client() as redis_client:
        if redis_client is None:
            logger.warning(
                "failed_to_mark_batch_processed",
                team_id=team_id,
                schema_id=schema_id,
                run_uuid=run_uuid,
                batch_index=batch_index,
            )
            return

        key = get_idempotency_key(team_id, schema_id, run_uuid, batch_index)
        redis_client.set(key, "1", ex=IDEMPOTENCY_TTL_SECONDS)
