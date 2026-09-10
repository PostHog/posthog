import re
from datetime import UTC, datetime

RAW_SESSION_IDENTIFIERS_START_MS = int(datetime(2026, 9, 11, 11, tzinfo=UTC).timestamp() * 1000)
_SESSION_UUID_V7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.IGNORECASE)


def uses_raw_session_identifiers(session_id: str) -> bool:
    if _SESSION_UUID_V7.fullmatch(session_id) is None:
        return False
    started_at_ms = int(session_id[:8] + session_id[9:13], 16)
    return started_at_ms >= RAW_SESSION_IDENTIFIERS_START_MS
