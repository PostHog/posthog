import gzip
import json

from prometheus_client import Enum
from pydantic import BaseModel
from redis import Redis

from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_DB_DATA_REDIS_TTL
from posthog.redis import get_client


class StateActivitiesEnum(Enum):
    SESSION_DB_DATA = "session_db_data"
    SESSION_SUMMARY = "session_summary"
    SESSION_GROUP_EXTRACTED_PATTERNS = "extracted_patterns"
    SESSION_GROUP_PATTERNS_ASSIGNMENTS = "patterns_assignments"


def get_redis_state_client(
    key_base: str | None = None,
    input_label: StateActivitiesEnum | None = None,
    output_label: StateActivitiesEnum | None = None,
    state_id: str | None = None,
) -> tuple[Redis, str | None, str | None]:
    """Get a Redis client and state keys for input and output data"""
    redis_client = get_client()
    redis_input_key, redis_output_key = None, None
    if key_base and input_label:
        redis_input_key = generate_state_key(key_base=key_base, label=input_label, state_id=state_id)
    if key_base and output_label:
        redis_output_key = generate_state_key(key_base=key_base, label=output_label, state_id=state_id)
    return redis_client, redis_input_key, redis_output_key


def generate_state_key(key_base: str, label: StateActivitiesEnum, state_id: str | None = None) -> str:
    if not state_id:
        raise ValueError("state_id is required")
    return f"{key_base}:{label}:{state_id}"


def _compress_redis_data(input_data: str) -> bytes:
    return gzip.compress(input_data.encode("utf-8"))


def _decompress_redis_data(raw_redis_data: bytes | str) -> str:
    if isinstance(raw_redis_data, bytes):
        return gzip.decompress(raw_redis_data).decode("utf-8")
    if isinstance(raw_redis_data, str):
        return raw_redis_data
    raise ValueError(f"Invalid Redis data type: {type(raw_redis_data)}")


def store_data_in_redis(redis_client: Redis, redis_key: str, data: str) -> None:
    compressed_data = _compress_redis_data(data)
    redis_client.setex(redis_key, SESSION_SUMMARIES_DB_DATA_REDIS_TTL, compressed_data)
    return None


def get_data_class_from_redis(
    redis_client: Redis, redis_key: str, label: StateActivitiesEnum, target_class: BaseModel
) -> BaseModel:
    redis_data_str = get_data_str_from_redis(redis_client=redis_client, redis_key=redis_key, label=label)
    try:
        return target_class(**json.loads(redis_data_str))  # type: ignore[operator]
    except Exception as err:
        raise ValueError(
            f"Failed to parse output data ({redis_data_str}) for Redis key {redis_key} ({label}): {err}"
        ) from err


def get_data_str_from_redis(redis_client: Redis, redis_key: str, label: StateActivitiesEnum) -> str:
    raw_redis_data = redis_client.get(redis_key)
    if not raw_redis_data:
        raise ValueError(f"Output data not found in Redis for key {redis_key} ({label})")
    try:
        redis_data_str = _decompress_redis_data(raw_redis_data)
        return redis_data_str
    except Exception as err:
        raise ValueError(
            f"Failed to decompress output data ({raw_redis_data}) for Redis key {redis_key} ({label}): {err}"
        ) from err
