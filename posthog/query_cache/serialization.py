from dataclasses import dataclass
from typing import Any, Optional

import structlog

from posthog.cache_utils import OrjsonJsonSerializer

logger = structlog.get_logger(__name__)

# Split cache format: magic + flags byte + 4-byte big-endian header length + header JSON + results JSON.
# Storing `results` as a separate JSON segment lets cache hits skip parsing (and later re-serializing)
# the results payload, which dominates CPU for large cached insights. Blobs without the magic prefix
# are the legacy single-JSON format and stay readable.
QUERY_CACHE_SPLIT_MAGIC = b"PHQC2\x00"
# The flags byte is a bitmask: readers must test individual bits, never compare the whole byte,
# so new flags can be added without breaking existing readers.
_SPLIT_FLAG_CUSTOM_NAMES = 0b00000001


@dataclass(frozen=True)
class CachedEntry:
    """A cached query response with the `results` segment kept as raw, unparsed JSON bytes."""

    header: dict
    results_bytes: Optional[bytes]
    """Raw JSON bytes of the `results` field; None means `header` is the full legacy response."""
    results_have_custom_names: bool = False
    """Whether any series/step in results carries a non-null custom_name (so a cache hit may need patching)."""
    cache_key: Optional[str] = None
    team_id: Optional[int] = None

    def as_full_response(self) -> Optional[dict]:
        """Merge the results segment back into the header; None on deserialization error."""
        if self.results_bytes is None:
            return self.header
        try:
            self.header["results"] = OrjsonJsonSerializer({}).loads(self.results_bytes)
        except Exception:
            logger.exception("query_cache_deserialize_error", cache_key=self.cache_key, team_id=self.team_id)
            return None
        return self.header


def _item_has_custom_name(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("custom_name") is not None:
        return True
    action = item.get("action")
    return isinstance(action, dict) and action.get("custom_name") is not None


def results_have_custom_names(results: list) -> bool:
    for item in results:
        if _item_has_custom_name(item):
            return True
        if isinstance(item, list) and any(_item_has_custom_name(step) for step in item):
            return True
    return False


def encode_split_cached_response(response: dict) -> bytes:
    serializer = OrjsonJsonSerializer({})
    results = response["results"]
    header = {key: value for key, value in response.items() if key != "results"}
    flags = _SPLIT_FLAG_CUSTOM_NAMES if results_have_custom_names(results) else 0
    header_bytes = serializer.dumps(header)
    return (
        QUERY_CACHE_SPLIT_MAGIC
        + bytes([flags])
        + len(header_bytes).to_bytes(4, "big")
        + header_bytes
        + serializer.dumps(results)
    )


def split_cached_response_bytes(
    cached_response_bytes: bytes, *, cache_key: Optional[str] = None, team_id: Optional[int] = None
) -> CachedEntry:
    serializer = OrjsonJsonSerializer({})
    if not cached_response_bytes.startswith(QUERY_CACHE_SPLIT_MAGIC):
        return CachedEntry(
            header=serializer.loads(cached_response_bytes), results_bytes=None, cache_key=cache_key, team_id=team_id
        )
    offset = len(QUERY_CACHE_SPLIT_MAGIC)
    flags = cached_response_bytes[offset]
    header_length = int.from_bytes(cached_response_bytes[offset + 1 : offset + 5], "big")
    header_start = offset + 5
    header = serializer.loads(cached_response_bytes[header_start : header_start + header_length])
    return CachedEntry(
        header=header,
        results_bytes=cached_response_bytes[header_start + header_length :],
        results_have_custom_names=bool(flags & _SPLIT_FLAG_CUSTOM_NAMES),
        cache_key=cache_key,
        team_id=team_id,
    )
