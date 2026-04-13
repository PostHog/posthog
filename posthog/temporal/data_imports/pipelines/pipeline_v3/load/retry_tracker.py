import json
from dataclasses import dataclass
from typing import Optional

from django.db import OperationalError

import structlog

from posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency import get_redis_client

logger = structlog.get_logger(__name__)

RETRY_KEY_PREFIX = "warehouse_pipelines:retry"
RETRY_TTL_SECONDS = 72 * 60 * 60  # 3 days (72 hours) same as idempotency / topic retention

MAX_RETRIES_TRANSIENT = 9
MAX_RETRIES_DEFAULT = 3  # non-transient, unknown (OOM), or any unclassified error

TRANSIENT_ERRORS = (
    OperationalError,  # Database connection issues
    ConnectionError,
    TimeoutError,
    OSError,
)


@dataclass
class RetryInfo:
    count: int = 0
    error_type: Optional[str] = None  # "transient" | "non_transient" | None
    last_error: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({"count": self.count, "error_type": self.error_type, "last_error": self.last_error})

    @classmethod
    def from_json(cls, data: str) -> "RetryInfo":
        parsed = json.loads(data)
        return cls(
            count=parsed.get("count", 0),
            error_type=parsed.get("error_type"),
            last_error=parsed.get("last_error"),
        )


class RetryExhaustedError(Exception):
    def __init__(self, retry_info: RetryInfo):
        self.retry_info = retry_info
        super().__init__(
            f"Retry limit exhausted: {retry_info.count} attempts, "
            f"error_type={retry_info.error_type}, last_error={retry_info.last_error}"
        )


def get_retry_key(team_id: int, schema_id: str, run_uuid: str, batch_index: int) -> str:
    return f"{RETRY_KEY_PREFIX}:{team_id}:{schema_id}:{run_uuid}:{batch_index}"


def get_retry_info(team_id: int, schema_id: str, run_uuid: str, batch_index: int) -> RetryInfo:
    with get_redis_client() as redis_client:
        if redis_client is None:
            return RetryInfo()

        key = get_retry_key(team_id, schema_id, run_uuid, batch_index)
        raw = redis_client.get(key)
        if raw is None:
            return RetryInfo()

        return RetryInfo.from_json(raw)


def increment_retry_count(team_id: int, schema_id: str, run_uuid: str, batch_index: int) -> RetryInfo:
    with get_redis_client() as redis_client:
        if redis_client is None:
            logger.warning(
                "failed_to_increment_retry_count",
                team_id=team_id,
                schema_id=schema_id,
                run_uuid=run_uuid,
                batch_index=batch_index,
            )
            return RetryInfo()

        key = get_retry_key(team_id, schema_id, run_uuid, batch_index)
        raw = redis_client.get(key)
        if raw is not None:
            info = RetryInfo.from_json(raw)
        else:
            info = RetryInfo()

        info.count += 1
        redis_client.set(key, info.to_json(), ex=RETRY_TTL_SECONDS)
        return info


def update_retry_error_type(
    team_id: int, schema_id: str, run_uuid: str, batch_index: int, error_type: str, last_error: str
) -> None:
    with get_redis_client() as redis_client:
        if redis_client is None:
            return

        key = get_retry_key(team_id, schema_id, run_uuid, batch_index)
        raw = redis_client.get(key)
        if raw is None:
            # Key vanished (TTL race or Redis blip after increment); recreate it.
            info = RetryInfo(error_type=error_type, last_error=last_error[:1000])
        else:
            info = RetryInfo.from_json(raw)
            info.error_type = error_type
            info.last_error = last_error[:1000]
        redis_client.set(key, info.to_json(), ex=RETRY_TTL_SECONDS)


def clear_retry_info(team_id: int, schema_id: str, run_uuid: str, batch_index: int) -> None:
    with get_redis_client() as redis_client:
        if redis_client is None:
            return

        key = get_retry_key(team_id, schema_id, run_uuid, batch_index)
        redis_client.delete(key)


def is_retry_exhausted(retry_info: RetryInfo) -> bool:
    if retry_info.error_type == "transient":
        return retry_info.count > MAX_RETRIES_TRANSIENT
    # non_transient, None (OOM/crash), or any unknown classification
    return retry_info.count > MAX_RETRIES_DEFAULT


def classify_error(error: Exception) -> str:
    if isinstance(error, TRANSIENT_ERRORS):
        return "transient"
    return "non_transient"
