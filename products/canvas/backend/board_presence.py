"""
Ephemeral pointer/viewport/selection broadcasting for canvas boards.

Presence lives in its own Redis stream per board: the op stream's ids ARE op
sequence numbers (see ``board_stream.py``), so presence cannot share it. Ids
here are auto-generated and entries are short-lived. Receivers always render the
latest ping per client and TTL-prune the rest, so a dropped event self-heals on
the next one.
"""

import json
from typing import Any

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

logger = structlog.get_logger(__name__)

PRESENCE_STREAM_KEY_PATTERN = "canvas:board:{{{team_id}:{board_id}}}:presence"

PRESENCE_TTL_SECONDS = 60 * 5
PRESENCE_MAX_LENGTH = 256
# On connect, replay this much recent presence so a fresh board sees the other
# people's cursors immediately.
PRESENCE_BACKFILL_MS = 10_000

PRESENCE_EVENT_TYPE = "presence"

# A selection ping carries ids, not fragments, so this cap only keeps one entry small.
PRESENCE_MAX_SELECTED_IDS = 50
PRESENCE_MAX_CARETS = 4

_DATA_KEY = b"data"


def publish_presence(
    team_id: int,
    board_id: str,
    *,
    client_id: str,
    user_id: int,
    user_name: str,
    user_uuid: str | None,
    user_email: str | None,
    cursor: dict[str, float] | None,
    viewport: dict[str, float] | None,
    selected_ids: list[str],
    carets: list[dict[str, str | None]] | None = None,
) -> None:
    """Fire-and-forget presence broadcast. Lossy by design: receivers always render
    the latest ping per client and TTL-prune the rest, so a dropped event self-heals
    on the next one."""
    client = redis_module.get_client()
    stream_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=team_id, board_id=board_id)
    payload = {
        "type": PRESENCE_EVENT_TYPE,
        "client_id": client_id,
        "user_id": user_id,
        "user_name": user_name,
        "user_uuid": user_uuid,
        "user_email": user_email,
        "cursor": cursor,
        "viewport": viewport,
        "selected_ids": selected_ids,
        "carets": carets or [],
    }

    try:
        client.xadd(
            stream_key,
            {"data": json.dumps(payload, separators=(",", ":"))},
            maxlen=PRESENCE_MAX_LENGTH,
            approximate=True,
        )
        client.expire(stream_key, PRESENCE_TTL_SECONDS)
    except redis_exceptions.RedisError as err:
        logger.warning(
            "canvas_board_presence_publish_error",
            stream_key=stream_key,
            board_id=board_id,
            error=str(err),
        )


def presence_sse_frame(fields: dict[bytes, bytes], *, stream_key: str, stream_id: str) -> bytes | None:
    """Presence frames deliberately omit the `id:` line so they never disturb Last-Event-ID."""
    try:
        data: Any = json.loads(fields[_DATA_KEY])
    except (json.JSONDecodeError, KeyError):
        logger.warning("canvas_board_invalid_payload", stream_key=stream_key, stream_id=stream_id)
        return None
    if data.get("type") != PRESENCE_EVENT_TYPE:
        logger.warning("canvas_board_unknown_payload", stream_key=stream_key, stream_id=stream_id)
        return None
    return f"event: presence\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()
