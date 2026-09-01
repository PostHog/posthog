"""
prosemirror-collab step buffering.

Steps are appended to the shared versioned content stream — see `stream.py` for the
transport and the CAS script that keeps versions linear.
"""

import json
from typing import Any, Literal

import structlog

from posthog import redis as redis_module
from posthog.collab.stream import (
    APPEND_ENTRIES_LUA,
    DATA_KEY,
    STREAM_MAX_LENGTH,
    STREAM_TTL_SECONDS,
    content_stream_key,
)
from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)


@frozen
class StepEntry:
    step: dict
    client_id: str


@frozen
class SubmitResult:
    # "accepted" - steps appended; `version` is the new top
    # "conflict" - caller is behind; `version` is the current top, `steps_since` is the missed range
    # "stale"    - missed range was trimmed (MAXLEN/TTL) or the stream was lost and the client's
    #              baseline no longer matches Postgres; caller must reload from Postgres
    status: Literal["accepted", "conflict", "stale"]
    version: int
    steps_since: list[StepEntry] | None = None


def submit_steps(
    namespace: str,
    team_id: int,
    document_id: str,
    client_id: str,
    steps_json: list[dict],
    last_seen_version: int,
    *,
    last_saved_version: int,
    user_id: int | None = None,
    user_name: str | None = None,
    cursor_head: int | None = None,
) -> SubmitResult:
    client = redis_module.get_client()
    stream_key = content_stream_key(namespace, team_id, document_id)

    # Presence (author + cursor) is constant for the whole batch — build once, spread per step.
    presence: dict[str, Any] = {
        k: v for k, v in (("user_id", user_id), ("user_name", user_name), ("cursor_head", cursor_head)) if v is not None
    }
    # Version isn't in the payload — the stream id (N-0) IS the version, and SSE delivers it as `id:`.
    serialized = [json.dumps({"step": step, "client_id": client_id, **presence}) for step in steps_json]

    script = client.register_script(APPEND_ENTRIES_LUA)
    accepted, version = script(
        keys=[stream_key],
        args=[last_seen_version, last_saved_version, STREAM_TTL_SECONDS, STREAM_MAX_LENGTH, *serialized],
    )

    if accepted == 1:
        return SubmitResult(status="accepted", version=version)
    if accepted == 2:
        return SubmitResult(status="stale", version=version)

    return fetch_missed_steps(stream_key, last_seen_version=last_seen_version, current_stream_version=version)


def fetch_missed_steps(stream_key: str, *, last_seen_version: int, current_stream_version: int) -> SubmitResult:
    # Client is somehow ahead of the stream — no missed range we could send.
    # The only safe response is "reload the document".
    if current_stream_version < last_seen_version:
        return SubmitResult(status="stale", version=current_stream_version)

    client = redis_module.get_client()
    raw = client.xrange(stream_key, min=f"({last_seen_version}-0", max=f"{current_stream_version}-0")

    missed_steps: list[StepEntry] = []
    for _stream_id, fields in raw:
        data = json.loads(fields[DATA_KEY])
        if "step" not in data or "client_id" not in data:
            continue
        missed_steps.append(StepEntry(step=data["step"], client_id=data["client_id"]))

    # MAXLEN/TTL trimmed part of the gap - incomplete rebase set, reload from Postgres
    gap_size = current_stream_version - last_seen_version
    if len(missed_steps) < gap_size:
        return SubmitResult(status="stale", version=current_stream_version)

    return SubmitResult(status="conflict", version=current_stream_version, steps_since=missed_steps)
