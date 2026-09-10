import json
from typing import Any

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

logger = structlog.get_logger(__name__)

PRESENCE_STREAM_KEY_PATTERN = "sketchpad:{{{team_id}:{sketchpad_id}}}:presence"

PRESENCE_TTL_SECONDS = 60 * 5
PRESENCE_MAX_LENGTH = 256
PRESENCE_BACKFILL_MS = 10_000

PRESENCE_EVENT_TYPE = "presence"

PRESENCE_MAX_SELECTED_IDS = 50
PRESENCE_MAX_CARETS = 4

_DATA_KEY = b"data"


def publish_presence(
    team_id: int,
    sketchpad_id: str,
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
    client = redis_module.get_client()
    stream_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=team_id, sketchpad_id=sketchpad_id)
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
            "sketchpad_presence_publish_error",
            stream_key=stream_key,
            sketchpad_id=sketchpad_id,
            error=str(err),
        )


def presence_sse_frame(fields: dict[bytes, bytes], *, stream_key: str, stream_id: str) -> bytes | None:
    try:
        data: Any = json.loads(fields[_DATA_KEY])
    except (json.JSONDecodeError, KeyError):
        logger.warning("sketchpad_invalid_payload", stream_key=stream_key, stream_id=stream_id)
        return None
    if data.get("type") != PRESENCE_EVENT_TYPE:
        logger.warning("sketchpad_unknown_payload", stream_key=stream_key, stream_id=stream_id)
        return None
    return f"event: presence\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()
