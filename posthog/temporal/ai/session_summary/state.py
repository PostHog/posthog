import gzip
import json

from prometheus_client import Enum
from redis import Redis

from ee.session_recordings.session_summary.summarize_session import SingleSessionSummaryLlmInputs
from posthog.redis import get_client


class StateActivitiesEnum(Enum):
    SESSION_DB_DATA = "session_db_data"
    SESSION_SUMMARY = "session_summary"
    SESSION_GROUP_SUMMARY = "session_group_summary"


def get_redis_state_client(
    input_key_base: str | None = None,
    input_label: StateActivitiesEnum | None = None,
    output_key_base: str | None = None,
    output_label: StateActivitiesEnum | None = None,
    state_id: str | None = None,
) -> tuple[Redis, str, str]:
    """Get a Redis client and state keys for input and output data"""
    redis_client = get_client()
    redis_input_key, redis_output_key = None, None
    if input_key_base is not None:
        if not input_label:
            raise ValueError("input_label is required if input_key_base is provided")
        redis_input_key = generate_state_key(key_base=input_key_base, label=input_label, state_id=state_id)
    if output_key_base is not None:
        if not output_label:
            raise ValueError("output_label is required if output_key_base is provided")
        redis_output_key = generate_state_key(key_base=output_key_base, label=output_label, state_id=state_id)
    return redis_client, redis_input_key, redis_output_key


def generate_state_key(key_base: str, label: StateActivitiesEnum, state_id: str | None = None) -> str:
    if not state_id:
        raise ValueError("state_id is required")
    return f"{key_base}:{label.value}:{state_id}"


def compress_redis_data(input_data: str) -> bytes:
    return gzip.compress(input_data.encode("utf-8"))


def _decompress_redis_data(raw_redis_data: bytes) -> str:
    if isinstance(raw_redis_data, bytes):
        return gzip.decompress(raw_redis_data).decode("utf-8")
    else:
        # Fallback for uncompressed data (if stored as string)
        return raw_redis_data


def get_single_session_summary_llm_input_from_redis(
    redis_client: Redis, redis_input_key: str
) -> SingleSessionSummaryLlmInputs:
    raw_redis_data = redis_client.get(redis_input_key)
    if not raw_redis_data:
        raise ValueError(f"Single session summary LLM input data not found in Redis for key {redis_input_key}")
    try:
        redis_data_str = _decompress_redis_data(raw_redis_data)
        redis_data = SingleSessionSummaryLlmInputs(**json.loads(redis_data_str))
    except Exception as e:
        raise ValueError(
            f"Failed to parse single session summary LLM input data ({raw_redis_data}) for Redis key {redis_input_key}: {e}"
        ) from e
    return redis_data


def get_single_session_summary_output_from_redis(redis_client: Redis, redis_output_key: str) -> str:
    raw_redis_data = redis_client.get(redis_output_key)
    if not raw_redis_data:
        raise ValueError(f"Single session summary LLM output data not found in Redis for key {redis_output_key}")
    try:
        redis_data_str = _decompress_redis_data(raw_redis_data)
    except Exception as e:
        raise ValueError(
            f"Failed to decompress single session summary LLM output data ({raw_redis_data}) for Redis key {redis_output_key}: {e}"
        ) from e
    return redis_data_str
