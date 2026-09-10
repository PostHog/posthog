import json
import time
import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from typing import Any

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from posthog import redis as redis_module
from posthog.api.streaming import sse_frame

DATA_KEY = b"data"
KEEPALIVE_COMMENT = b": keepalive\n\n"
STREAM_ERROR_FRAME = sse_frame({"error": "stream error"}, event="error")
STREAM_BLOCK_MS = 15_000
STREAM_LIFETIME_SECONDS = 5 * 60
STREAM_READ_COUNT = 32
PRESENCE_TTL_SECONDS = 5 * 60
PRESENCE_MAX_LENGTH = 256
PRESENCE_BACKFILL_MS = 10_000
PRESENCE_EVENT_TYPE = "presence"

logger = structlog.get_logger(__name__)


def publish_presence_entry(stream_key: str, payload: Mapping[str, Any], *, log_name: str) -> None:
    client = redis_module.get_client()
    try:
        client.xadd(
            stream_key,
            {"data": json.dumps(payload, separators=(",", ":"))},
            maxlen=PRESENCE_MAX_LENGTH,
            approximate=True,
        )
        client.expire(stream_key, PRESENCE_TTL_SECONDS)
    except RedisError as err:
        logger.warning(f"{log_name}_presence_publish_error", stream_key=stream_key, error=str(err))


def presence_sse_frame(fields: dict[bytes, bytes], *, stream_key: str, stream_id: str, log_name: str) -> bytes | None:
    data = _decode_entry(fields, stream_key=stream_key, stream_id=stream_id, log_name=log_name)
    if data is None:
        return None
    if data.get("type") != PRESENCE_EVENT_TYPE:
        logger.warning(f"{log_name}_unknown_payload", stream_key=stream_key, stream_id=stream_id)
        return None
    return sse_frame(data, event=PRESENCE_EVENT_TYPE)


def _decode_entry(
    fields: dict[bytes, bytes], *, stream_key: str, stream_id: str, log_name: str
) -> dict[str, Any] | None:
    try:
        data = json.loads(fields[DATA_KEY])
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
        pass
    logger.warning(f"{log_name}_invalid_payload", stream_key=stream_key, stream_id=stream_id)
    return None


async def tail_streams(
    *,
    client: Redis,
    content_key: str,
    content_id: str,
    presence_key: str,
    log_name: str,
    frame_for_entry: Callable[[str, dict[str, Any]], bytes | None],
    should_continue: Callable[[], Awaitable[bool]] | None = None,
    batch_interval: float = 0.0,
) -> AsyncGenerator[bytes]:
    try:
        seconds, micros = await client.time()
        now_ms = seconds * 1000 + micros // 1000
    except RedisError:
        now_ms = int(time.time() * 1000)
    presence_id = f"{max(0, now_ms - PRESENCE_BACKFILL_MS)}-0"
    try:
        async with asyncio.timeout(STREAM_LIFETIME_SECONDS):
            while True:
                try:
                    messages = await client.xread(
                        {content_key: content_id, presence_key: presence_id},
                        block=STREAM_BLOCK_MS,
                        count=STREAM_READ_COUNT,
                    )
                except RedisError as err:
                    logger.warning(f"{log_name}_stream_error", stream_key=content_key, error=str(err))
                    yield STREAM_ERROR_FRAME
                    return
                if should_continue is not None and not await should_continue():
                    return
                if not messages:
                    yield KEEPALIVE_COMMENT
                    continue
                for key, entries in messages:
                    key_name = key.decode() if isinstance(key, bytes) else key
                    for stream_id, fields in entries:
                        entry_id = stream_id.decode()
                        if key_name == presence_key:
                            presence_id = entry_id
                            frame = presence_sse_frame(
                                fields, stream_key=presence_key, stream_id=entry_id, log_name=log_name
                            )
                        else:
                            content_id = entry_id
                            data = _decode_entry(fields, stream_key=content_key, stream_id=entry_id, log_name=log_name)
                            frame = frame_for_entry(entry_id, data) if data is not None else None
                        if frame is not None:
                            yield frame
                await asyncio.sleep(
                    0 if any(len(entries) >= STREAM_READ_COUNT for _, entries in messages) else batch_interval
                )
    except TimeoutError:
        return
