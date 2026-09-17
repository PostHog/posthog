"""Port of nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format.ts.

The mirror decides whether a session is stored under raw or pseudonymized ids from
the UUIDv7 timestamp in the session id alone, so the export has to decide from the
same input: `min_first_timestamp` is a ClickHouse aggregate over the session's rows
and can land on the other side of the cutoff, and a session id that is not a UUIDv7
has no raw-id row in the mirror at any timestamp.

Parity is pinned against the mirror's own
`ml-mirror/session-identifier-format-cases.json` fixture.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

RAW_SESSION_IDENTIFIERS_START = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
RAW_SESSION_IDENTIFIERS_START_MS = int(RAW_SESSION_IDENTIFIERS_START.timestamp() * 1000)

# `Date.UTC(10000, 0, 1)` in the Node source: past it the session's month is unrepresentable.
MAX_SESSION_START_MS = 253_402_300_800_000

_UUID_V7_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def session_start_timestamp_from_uuid_v7(session_id: str) -> int | None:
    if not _UUID_V7_RE.match(session_id):
        return None
    timestamp = int(session_id[0:8] + session_id[9:13], 16)
    return timestamp if timestamp > 0 else None


def uses_raw_session_identifiers(session_id: str) -> bool:
    started_at = session_start_timestamp_from_uuid_v7(session_id)
    return started_at is not None and RAW_SESSION_IDENTIFIERS_START_MS <= started_at < MAX_SESSION_START_MS
