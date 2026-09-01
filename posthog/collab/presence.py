"""
Ephemeral broadcasting for document collaboration: carets, and short "something changed"
signals such as a new discussion post.

This traffic lives in its own Redis stream per document: the content stream's ids ARE
document versions (a CAS invariant), so it cannot share them. Ids here are auto-generated
and entries are short-lived — receivers always render the latest ping per client and
TTL-prune the rest, so a dropped event self-heals on the next one.
"""

import json
from collections.abc import Collection
from typing import Any

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

logger = structlog.get_logger(__name__)

PRESENCE_STREAM_KEY_PATTERN = "{namespace}:collab:{{{team_id}:{document_id}}}:presence"

PRESENCE_TTL_SECONDS = 60 * 5
PRESENCE_MAX_LENGTH = 256
# On connect, replay this much recent presence so a fresh tab sees existing carets immediately.
PRESENCE_BACKFILL_MS = 10_000

PRESENCE_EVENT_TYPE = "presence"

_DATA_KEY = b"data"


def presence_stream_key(namespace: str, team_id: int, document_id: str) -> str:
    return PRESENCE_STREAM_KEY_PATTERN.format(namespace=namespace, team_id=team_id, document_id=document_id)


def publish_presence(
    namespace: str,
    team_id: int,
    document_id: str,
    *,
    client_id: str,
    user_id: int,
    user_name: str,
    version: int,
    cursor: dict[str, Any],
) -> None:
    """Fire-and-forget caret broadcast. Lossy by design: receivers always render the latest
    ping per client and TTL-prune the rest, so a dropped event self-heals on the next one."""
    publish_ephemeral_event(
        namespace,
        team_id,
        document_id,
        event_type=PRESENCE_EVENT_TYPE,
        payload={
            "client_id": client_id,
            "user_id": user_id,
            "user_name": user_name,
            "version": version,
            "cursor": cursor,
        },
    )


def publish_ephemeral_event(
    namespace: str,
    team_id: int,
    document_id: str,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Fire-and-forget signal to everyone tailing this document. Lossy: a receiver that
    misses one refetches on the next, so never carry state that has no other source."""
    client = redis_module.get_client()
    stream_key = presence_stream_key(namespace, team_id, document_id)

    try:
        client.xadd(
            stream_key,
            {"data": json.dumps({"type": event_type, **payload}, separators=(",", ":"))},
            maxlen=PRESENCE_MAX_LENGTH,
            approximate=True,
        )
        client.expire(stream_key, PRESENCE_TTL_SECONDS)
    except redis_exceptions.RedisError as err:
        logger.warning(
            f"{namespace}_collab_presence_publish_error",
            stream_key=stream_key,
            document_id=document_id,
            error=str(err),
        )


def ephemeral_sse_frame(
    fields: dict[bytes, bytes],
    *,
    namespace: str,
    stream_key: str,
    stream_id: str,
    allowed_types: Collection[str] = (PRESENCE_EVENT_TYPE,),
) -> bytes | None:
    """Ephemeral frames deliberately omit the `id:` line so they never disturb Last-Event-ID."""
    try:
        data = json.loads(fields[_DATA_KEY])
    except (json.JSONDecodeError, KeyError):
        logger.warning(f"{namespace}_collab_invalid_payload", stream_key=stream_key, stream_id=stream_id)
        return None
    event_type = data.get("type")
    if event_type not in allowed_types:
        logger.warning(f"{namespace}_collab_unknown_payload", stream_key=stream_key, stream_id=stream_id)
        return None
    return f"event: {event_type}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def presence_sse_frame(fields: dict[bytes, bytes], *, namespace: str, stream_key: str, stream_id: str) -> bytes | None:
    return ephemeral_sse_frame(fields, namespace=namespace, stream_key=stream_key, stream_id=stream_id)
