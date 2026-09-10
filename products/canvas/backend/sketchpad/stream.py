import json
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import aclosing
from typing import Any

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module
from posthog.api.streaming import sse_frame
from posthog.collab_stream import STREAM_ERROR_FRAME, tail_streams

from products.canvas.backend.sketchpad.presence import PRESENCE_STREAM_KEY_PATTERN

logger = structlog.get_logger(__name__)

OPS_STREAM_KEY_PATTERN = "sketchpad:{{{team_id}:{sketchpad_id}}}:ops"

OPS_STREAM_TTL_SECONDS = 60 * 60 * 24
OPS_STREAM_MAX_LENGTH = 5000
OPS_STREAM_MAX_PAYLOAD_BYTES = 64 * 1024
STREAM_BATCH_INTERVAL_SECONDS = 0.1

ACCESS_RECHECK_SECONDS = 15.0

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
            if len(payload.encode()) > OPS_STREAM_MAX_PAYLOAD_BYTES:
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

        try:
            client.xadd(
                stream_key,
                {"data": json.dumps({"type": RELOAD_EVENT_TYPE, "since": entries[0]["seq"] - 1})},
                id=f"{entries[-1]['seq']}-1",
                maxlen=OPS_STREAM_MAX_LENGTH,
                approximate=True,
            )
            client.expire(stream_key, OPS_STREAM_TTL_SECONDS)
        except redis_exceptions.RedisError:
            pass


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
    gap = oldest_seq is None or oldest_seq > last_seq + 1
    return last_event_id, last_seq if gap else None


def reload_sse_frame(since: int) -> bytes:
    payload = {"type": RELOAD_EVENT_TYPE, "since": since}
    return sse_frame(payload, event=RELOAD_EVENT_TYPE)


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
        yield STREAM_ERROR_FRAME
        return

    if reload_since is not None:
        yield reload_sse_frame(reload_since)
    last_access_check = time.monotonic()

    async def should_continue() -> bool:
        nonlocal last_access_check
        now = time.monotonic()
        if now - last_access_check < ACCESS_RECHECK_SECONDS:
            return True
        last_access_check = now
        return await can_read()

    def frame_for_entry(stream_id: str, data: dict[str, Any]) -> bytes | None:
        if data.get("type") == RELOAD_EVENT_TYPE:
            return reload_sse_frame(data["since"])
        if data.get("type") == OP_EVENT_TYPE:
            return sse_frame(data, event=OP_EVENT_TYPE, event_id=stream_id)
        logger.warning("sketchpad_unknown_payload", stream_key=ops_key, stream_id=stream_id)
        return None

    async with aclosing(
        tail_streams(
            client=client,
            content_key=ops_key,
            content_id=ops_id,
            presence_key=presence_key,
            log_name="sketchpad",
            frame_for_entry=frame_for_entry,
            should_continue=should_continue,
            batch_interval=STREAM_BATCH_INTERVAL_SECONDS,
        )
    ) as frames:
        async for frame in frames:
            yield frame
