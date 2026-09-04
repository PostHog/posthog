"""
Live Redis-stream transport for one canvas board.

Two streams per board:

- an op stream, whose entry id carries the op ``seq`` (``{seq}-0``), written by
  ``board_log.append_ops`` after its transaction commits
- the ephemeral presence stream in ``board_presence.py``

This module owns the op stream key layout, the publish, and the SSE tailer that
fans both streams out to clients. Redis is only the fast path: the database log
stays the record of truth, so a client that reconnects past the end of the
stream is told to page ``ops/?since=`` instead of missing an op.
"""

import json
import time
import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from typing import Any

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

from products.canvas.backend.board_presence import PRESENCE_BACKFILL_MS, PRESENCE_STREAM_KEY_PATTERN, presence_sse_frame

logger = structlog.get_logger(__name__)

OPS_STREAM_KEY_PATTERN = "canvas:board:{{{team_id}:{board_id}}}:ops"

OPS_STREAM_TTL_SECONDS = 60 * 60 * 24  # 1 day, refreshed on every XADD
OPS_STREAM_MAX_LENGTH = 5000
OPS_STREAM_MAX_PAYLOAD_BYTES = 64 * 1024
STREAM_READ_COUNT = 32
STREAM_BATCH_INTERVAL_SECONDS = 0.1

# Max XREAD wait, proxies idle-kill connections around 60s
STREAM_BLOCK_MS = 15_000

# SSE lifetime cap. The browser reconnects with Last-Event-ID.
STREAM_LIFETIME_SECONDS = 5 * 60

DATA_KEY = b"data"
KEEPALIVE_COMMENT = b": keepalive\n\n"
EARLIEST_STREAM_ID = "0-0"

OP_EVENT_TYPE = "op"
RELOAD_EVENT_TYPE = "reload"


def publish_ops(team_id: int, board_id: str, entries: Sequence[Mapping[str, Any]]) -> None:
    """Fan committed ops out to the board's live stream, newest last.

    Each entry is one log entry as ``ops/`` returns it, and its ``seq`` becomes
    the stream id. Failures are logged, not raised: a client that misses an
    entry here reads it from the database log.
    """
    if not entries:
        return
    client = redis_module.get_client()
    stream_key = OPS_STREAM_KEY_PATTERN.format(team_id=team_id, board_id=board_id)
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
            "canvas_board_ops_publish_error",
            stream_key=stream_key,
            board_id=board_id,
            error=str(err),
        )


def seq_from_stream_id(stream_id: str) -> int | None:
    """The op seq an op-stream id carries, or None when the id is not one of ours."""
    head = stream_id.split("-", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def resume_position(last_event_id: str, oldest_stream_id: str | None) -> tuple[str, int | None]:
    """Where to tail the op stream from, and the seq to reload the log from.

    A reload seq is returned when Redis no longer holds the op after
    ``last_event_id``, because the client must never skip an op silently.
    """
    last_seq = seq_from_stream_id(last_event_id)
    if last_seq is None:
        return EARLIEST_STREAM_ID, 0
    oldest_seq = seq_from_stream_id(oldest_stream_id) if oldest_stream_id is not None else None
    if oldest_seq is None or oldest_seq > last_seq + 1:
        return EARLIEST_STREAM_ID, last_seq
    return last_event_id, None


def reload_sse_frame(since: int) -> bytes:
    """Asks the client to page GET ops/?since= for the ops the stream no longer holds.

    Carries no `id:` line: a reload is an instruction, not a stream position.
    """
    payload = {"type": RELOAD_EVENT_TYPE, "since": since}
    return f"event: reload\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


async def stream_board_sse(
    team_id: int,
    board_id: str,
    *,
    can_read: Callable[[], Awaitable[bool]],
    last_event_id: str | None = None,
) -> AsyncGenerator[bytes]:
    """
    Tail this board's op and presence Redis streams from last_event_id (or from now
    if None). Yields one SSE frame per op and per presence ping, plus a keepalive
    comment during idle gaps.

    Only op frames carry an `id:` line: Last-Event-ID must resume the sequenced op
    stream, never the ephemeral presence stream (which backfills the last few
    seconds instead).
    """
    if not await can_read():
        return
    client = redis_module.get_async_client()
    ops_key = OPS_STREAM_KEY_PATTERN.format(team_id=team_id, board_id=board_id)
    presence_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=team_id, board_id=board_id)

    reload_since: int | None = None
    try:
        if last_event_id is None:
            # Resolve "now" to a concrete id up front: with two streams in one XREAD, "$"
            # would re-evaluate on every call and skip ops appended while a presence batch
            # was being processed.
            newest = await client.xrevrange(ops_key, "+", "-", count=1)
            ops_id = newest[0][0].decode() if newest else EARLIEST_STREAM_ID
        else:
            oldest = await client.xrange(ops_key, "-", "+", count=1)
            ops_id, reload_since = resume_position(last_event_id, oldest[0][0].decode() if oldest else None)
    except redis_exceptions.RedisError as err:
        logger.warning("canvas_board_stream_error", board_id=board_id, error=str(err))
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
                    logger.warning("canvas_board_stream_error", board_id=board_id, error=str(err))
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
                            logger.warning("canvas_board_invalid_payload", stream_key=ops_key, stream_id=ops_id)
                            continue
                        if data.get("type") == RELOAD_EVENT_TYPE:
                            yield reload_sse_frame(data["since"])
                            continue
                        if data.get("type") != OP_EVENT_TYPE:
                            logger.warning("canvas_board_unknown_payload", stream_key=ops_key, stream_id=ops_id)
                            continue
                        yield (f"id: {ops_id}\nevent: op\ndata: {json.dumps(data, separators=(',', ':'))}\n\n").encode()

                # cooperative yield: prevents tight-loop monopolization when XREAD doesn't block
                await asyncio.sleep(
                    0
                    if any(len(entries) >= STREAM_READ_COUNT for _, entries in messages)
                    else STREAM_BATCH_INTERVAL_SECONDS
                )
    except TimeoutError:
        # Lifetime cap hit; the client reconnects with Last-Event-ID against a fresh worker
        return
