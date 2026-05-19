from contextlib import contextmanager

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper

logger = structlog.get_logger(__name__)

IDEMPOTENCY_KEY_PREFIX = "warehouse_pipelines:processed"
IDEMPOTENCY_TTL_SECONDS = 72 * 60 * 60  # 3 days (72 hours) same as the topic retention period


@contextmanager
def get_redis_client():
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


def get_idempotency_key(team_id: int, schema_id: str, run_uuid: str, batch_index: int) -> str:
    """Generate a unique idempotency key for a batch."""
    return f"{IDEMPOTENCY_KEY_PREFIX}:{team_id}:{schema_id}:{run_uuid}:{batch_index}"


def is_batch_already_processed(
    team_id: int,
    schema_id: str,
    run_uuid: str,
    batch_index: int,
    delta_table_helper: DeltaTableHelper | None = None,
) -> bool:
    """Check if a batch has already been processed.

    Fast path: the Redis dedup flag written by `mark_batch_as_processed` after a
    successful delta write.

    Slow path (post-crash recovery): if Redis has no flag and a `DeltaTableHelper`
    is provided, scan recent delta commits for a commit whose userMetadata matches
    this (run_uuid, batch_index). This catches the narrow writer-crash window
    between `write_to_deltalake` committing and `mark_batch_as_processed` running —
    on Kafka redelivery we'd otherwise re-write the same batch and produce
    duplicate rows.
    """
    with get_redis_client() as redis_client:
        if redis_client is not None:
            key = get_idempotency_key(team_id, schema_id, run_uuid, batch_index)
            if redis_client.exists(key) == 1:
                return True

    if delta_table_helper is None:
        return False

    try:
        return async_to_sync(delta_table_helper.has_batch_been_committed)(run_uuid, batch_index)
    except Exception as e:
        # Failing open here would re-enable the duplicate-write race we're fixing,
        # so we log and surface the error to the caller (which will retry the message).
        logger.warning(
            "delta_history_idempotency_check_failed",
            team_id=team_id,
            schema_id=schema_id,
            run_uuid=run_uuid,
            batch_index=batch_index,
            error=str(e),
        )
        capture_exception(e)
        raise


def mark_batch_as_processed(team_id: int, schema_id: str, run_uuid: str, batch_index: int) -> None:
    """Mark a batch as processed in the cache."""
    with get_redis_client() as redis_client:
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
