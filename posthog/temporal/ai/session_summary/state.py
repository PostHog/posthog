import gzip
import json

from enum import Enum
from typing import TypeVar
from redis import asyncio as aioredis

from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_DB_DATA_REDIS_TTL
from posthog.redis import get_async_client

T = TypeVar("T")


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
) -> tuple[aioredis.Redis, str | None, str | None]:
    """Return a Redis client and generated state keys.

    Parameters
    ----------
    key_base:
        Base used for the Redis keys. When provided together with
        `input_label` or `output_label` a state key will be generated.
    input_label:
        Activity label describing the input data.
    output_label:
        Activity label describing the output data.
    state_id:
        Unique identifier appended to the generated keys. Required when key
        generation is requested.

    Returns
    -------
    tuple[Redis, str | None, str | None]
        The Redis client instance together with the generated input and output
        keys. `None` is returned for a key when its label was not supplied.
    """
    redis_client = get_async_client()
    redis_input_key, redis_output_key = None, None
    if key_base and input_label:
        redis_input_key = generate_state_key(key_base=key_base, label=input_label, state_id=state_id)
    if key_base and output_label:
        redis_output_key = generate_state_key(key_base=key_base, label=output_label, state_id=state_id)
    return redis_client, redis_input_key, redis_output_key


def generate_state_key(key_base: str, label: StateActivitiesEnum, state_id: str | None = None) -> str:
    """Construct a deterministic Redis key for workflow state.

    Parameters
    ----------
    key_base:
        Base prefix used for all state keys.
    label:
        Activity label describing the type of stored data.
    state_id:
        Unique identifier for the session(s) affected.

    Returns
    -------
    str
        Formatted key for Redis.
    """
    if not state_id:
        raise ValueError("state_id is required")
    return f"{key_base}:{label.value}:{state_id}"


def _compress_redis_data(input_data: str) -> bytes:
    return gzip.compress(input_data.encode("utf-8"))


def _decompress_redis_data(raw_redis_data: bytes | str) -> str:
    """Decode data retrieved from Redis. If data is `bytes` it is assumed to be
    gzip-compressed and will be decompressed. `str` values are returned unchanged."""
    if isinstance(raw_redis_data, bytes):
        return gzip.decompress(raw_redis_data).decode("utf-8")
    if isinstance(raw_redis_data, str):
        return raw_redis_data
    raise ValueError(f"Invalid Redis data type: {type(raw_redis_data)}")


async def store_data_in_redis(
    redis_client: aioredis.Redis, redis_key: str | None, data: str, ttl: int = SESSION_SUMMARIES_DB_DATA_REDIS_TTL
) -> None:
    """Compress and store data in Redis with an expiry time."""
    if not redis_key:
        raise ValueError(f"Redis key is required to store data in Redis ({data})")
    compressed_data = _compress_redis_data(data)
    await redis_client.setex(redis_key, ttl, compressed_data)
    return None


async def get_data_class_from_redis(
    redis_client: aioredis.Redis, redis_key: str | None, label: StateActivitiesEnum, target_class: type[T]
) -> T:
    """Load and parse a dataclass instance stored as JSON in Redis.

    Parameters
    ----------
    redis_client:
        Redis client used to fetch the value.
    redis_key:
        Key from which the JSON value is retrieved.
    label:
        Activity label used solely for error messages.
    target_class:
        Dataclass type into which the JSON will be loaded.

    Returns
    -------
    T
        Instance of `target_class` reconstructed from the stored JSON.
    """
    if not redis_key:
        raise ValueError(f"Redis key is required for {label.value} to extract data from Redis ({target_class})")
    redis_data_str = await get_data_str_from_redis(redis_client=redis_client, redis_key=redis_key, label=label)
    try:
        return target_class(**json.loads(redis_data_str))
    except Exception as err:
        raise ValueError(
            f"Failed to parse output data ({redis_data_str}) for Redis key {redis_key} ({label.value}): {err}"
        ) from err


async def get_data_str_from_redis(
    redis_client: aioredis.Redis, redis_key: str | None, label: StateActivitiesEnum
) -> str:
    """Retrieve and decompress a string value from Redis."""
    if not redis_key:
        raise ValueError(f"Redis key is required to get data from Redis ({label.value})")
    raw_redis_data = await redis_client.get(redis_key)
    if not raw_redis_data:
        raise ValueError(f"Output data not found in Redis for key {redis_key} ({label.value})")
    try:
        redis_data_str = _decompress_redis_data(raw_redis_data)
        return redis_data_str
    except Exception as err:
        raise ValueError(
            f"Failed to decompress output data ({raw_redis_data}) for Redis key {redis_key} ({label.value}): {err}"
        ) from err
