"""
Server-authoritative document collaboration over Redis streams.

One versioned content stream per document, where the stream id (``N-x``) carries the
document version, plus a separate lossy presence stream for carets. Callers pick a
``namespace`` (``"notebook"``, ``"doc"``, …) that prefixes both keys, so products share
the transport without sharing key space.

- ``stream.py`` — key layout, the version-CAS Lua script, the SSE tailer
- ``steps.py`` — prosemirror-collab step submission on top of the CAS script
- ``presence.py`` — ephemeral caret broadcasting
"""

from posthog.collab.presence import (
    PRESENCE_BACKFILL_MS as PRESENCE_BACKFILL_MS,
    PRESENCE_EVENT_TYPE as PRESENCE_EVENT_TYPE,
    PRESENCE_MAX_LENGTH as PRESENCE_MAX_LENGTH,
    PRESENCE_STREAM_KEY_PATTERN as PRESENCE_STREAM_KEY_PATTERN,
    PRESENCE_TTL_SECONDS as PRESENCE_TTL_SECONDS,
    presence_sse_frame as presence_sse_frame,
    presence_stream_key as presence_stream_key,
    publish_presence as publish_presence,
)
from posthog.collab.steps import (
    StepEntry as StepEntry,
    SubmitResult as SubmitResult,
    fetch_missed_steps as fetch_missed_steps,
    submit_steps as submit_steps,
)
from posthog.collab.stream import (
    APPEND_ENTRIES_LUA as APPEND_ENTRIES_LUA,
    DATA_KEY as DATA_KEY,
    KEEPALIVE_COMMENT as KEEPALIVE_COMMENT,
    STREAM_BLOCK_MS as STREAM_BLOCK_MS,
    STREAM_KEY_PATTERN as STREAM_KEY_PATTERN,
    STREAM_LIFETIME_SECONDS as STREAM_LIFETIME_SECONDS,
    STREAM_MAX_LENGTH as STREAM_MAX_LENGTH,
    STREAM_READ_COUNT as STREAM_READ_COUNT,
    STREAM_TTL_SECONDS as STREAM_TTL_SECONDS,
    UPDATE_EVENT_TYPE as UPDATE_EVENT_TYPE,
    content_stream_key as content_stream_key,
    stream_collab_sse as stream_collab_sse,
)
