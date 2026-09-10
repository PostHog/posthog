import json
import time
import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from typing import Any

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

from products.canvas.backend.sketchpad_presence import (
    PRESENCE_BACKFILL_MS,
    PRESENCE_STREAM_KEY_PATTERN,
    presence_sse_frame,
)

logger = structlog.get_logger(__name__)

OPS_STREAM_KEY_PATTERN = "sketchpad:{{{team_id}:{sketchpad_id}}}:ops"

OPS_STREAM_TTL_SECONDS = 60 * 60 * 24
OPS_STREAM_MAX_LENGTH = 5000
OPS_STREAM_MAX_PAYLOAD_BYTES = 64 * 1024
STREAM_READ_COUNT = 32
STREAM_BATCH_INTERVAL_SECONDS = 0.1

STREAM_BLOCK_MS = 15_000

STREAM_LIFETIME_SECONDS = 5 * 60

DATA_KEY = b"data"
KEEPALIVE_COMMENT = b": keepalive\n\n"
EARLIEST_STREAM_ID = "0-0"

OP_EVENT_TYPE = "op"
RELOAD_EVENT_TYPE = "reload"


def publish_ops(team_id: int, sketchpad_id: str, entries: Sequence[Mapping[str, Any]]) -> None:
    if not entries:
        return
    client = redis_module.get_client()
    stream_key = OPS_STREAM_KEY_PATTERN.format(team_id=team_id, sketchpad_id=sketchpad_id)
    try:
        for entry in entries:
            payload = json.dumps({"type": OP_EVENT_TYPE, **entry}, separators=(",", ":"))
            if len(payload) > OPS_STREAM_MAX_PAYLOAD_BYTES:
                payload = json.dumps({"type": RELOAD_EVENT_TYPE, "since": entry["seq"] - 1}, separators=(",", ":"))
            client.xadd(
                stream_key,
                {"data": payload},
                id=f"{entry['seq']}-0",
                maxlen=OPS_STREAM_MAX_LENGTH,
                approximate=True,
            )
        client.expire(stream_key, OPS_STREAM_TTL_SECONDS)
    except redis_exceptions.RedisError as err:
        logger.warning(
            "sketchpad_ops_publish_error",
            stream_key=stream_key,
            sketchpad_id=sketchpad_id,
            error=str(err),
        )


def seq_from_stream_id(stream_id: str) -> int | None:
    head = stream_id.split("-", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def resume_position(last_event_id: str, oldest_stream_id: str | None) -> tuple[str, int | None]:
    last_seq = seq_from_stream_id(last_event_id)
    if last_seq is None:
        return EARLIEST_STREAM_ID, 0
    oldest_seq = seq_from_stream_id(oldest_stream_id) if oldest_stream_id is not None else None
    if oldest_seq is None or oldest_seq > last_seq + 1:
        return EARLIEST_STREAM_ID, last_seq
    return last_event_id, None


def reload_sse_frame(since: int) -> bytes:
    payload = {"type": RELOAD_EVENT_TYPE, "since": since}
    return f"event: reload\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


async def stream_sketchpad_sse(
    team_id: int,
    sketchpad_id: str,
    *,
    can_read: Callable[[], Awaitable[bool]],
    last_event_id: str | None = None,
) -> AsyncGenerator[bytes]:
    if not await can_read():
        return
    client = redis_module.get_async_client()
    ops_key = OPS_STREAM_KEY_PATTERN.format(team_id=team_id, sketchpad_id=sketchpad_id)
    presence_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=team_id, sketchpad_id=sketchpad_id)

    reload_since: int | None = None
    try:
        if last_event_id is None:
            newest = await client.xrevrange(ops_key, "+", "-", count=1)
            ops_id = newest[0][0].decode() if newest else EARLIEST_STREAM_ID
        else:
            oldest = await client.xrange(ops_key, "-", "+", count=1)
            ops_id, reload_since = resume_position(last_event_id, oldest[0][0].decode() if oldest else None)
    except redis_exceptions.RedisError as err:
        logger.warning("sketchpad_stream_error", sketchpad_id=sketchpad_id, error=str(err))
        yield b'event: error\ndata: {"error":"stream error"}\n\n'
        return

    if reload_since is not None:
        yield reload_sse_frame(reload_since)
    presence_id = f"{max(0, int(time.time() * 1000) - PRESENCE_BACKFILL_MS)}-0"

    try:
        async with asyncio.timeout(STREAM_LIFETIME_SECONDS):
            while True:
                try:
                    messages = await client.xread(
                        {ops_key: ops_id, presence_key: presence_id},
                        block=STREAM_BLOCK_MS,
                        count=STREAM_READ_COUNT,
                    )
                except redis_exceptions.RedisError as err:
                    logger.warning("sketchpad_stream_error", sketchpad_id=sketchpad_id, error=str(err))
                    yield b'event: error\ndata: {"error":"stream error"}\n\n'
                    return

                if not await can_read():
                    return

                if not messages:
                    yield KEEPALIVE_COMMENT
                    continue

                for key, entries in messages:
                    key_name = key.decode() if isinstance(key, bytes) else key
                    if key_name == presence_key:
                        for stream_id, fields in entries:
                            presence_id = stream_id.decode()
                            frame = presence_sse_frame(fields, stream_key=presence_key, stream_id=presence_id)
                            if frame is not None:
                                yield frame
                        continue

                    for stream_id, fields in entries:
                        ops_id = stream_id.decode()
                        try:
                            data = json.loads(fields[DATA_KEY])
                        except json.JSONDecodeError:
                            logger.warning("sketchpad_invalid_payload", stream_key=ops_key, stream_id=ops_id)
                            continue
                        if data.get("type") == RELOAD_EVENT_TYPE:
                            yield reload_sse_frame(data["since"])
                            continue
                        if data.get("type") != OP_EVENT_TYPE:
                            logger.warning("sketchpad_unknown_payload", stream_key=ops_key, stream_id=ops_id)
                            continue
                        yield (f"id: {ops_id}\nevent: op\ndata: {json.dumps(data, separators=(',', ':'))}\n\n").encode()

                await asyncio.sleep(
                    0
                    if any(len(entries) >= STREAM_READ_COUNT for _, entries in messages)
                    else STREAM_BATCH_INTERVAL_SECONDS
                )
    except TimeoutError:
        return
