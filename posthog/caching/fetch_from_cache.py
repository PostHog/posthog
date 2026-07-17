from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import structlog
from prometheus_client import Counter

from posthog.schema import QueryTiming

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.caching.query_cache_routing import get_query_cache

logger = structlog.get_logger(__name__)

insight_cache_read_counter = Counter(
    "posthog_cloud_insight_cache_read",
    "A read from the redis insight cache",
    labelnames=["result"],
)

# Split cache format: magic + flags byte + 4-byte big-endian header length + header JSON + results JSON.
# Storing `results` as a separate JSON segment lets cache hits skip parsing (and later re-serializing)
# the results payload, which dominates CPU for large cached insights. Blobs without the magic prefix
# are the legacy single-JSON format and stay readable.
QUERY_CACHE_SPLIT_MAGIC = b"PHQC2\x00"
# The flags byte is a bitmask: readers must test individual bits, never compare the whole byte,
# so new flags can be added without breaking existing readers.
_SPLIT_FLAG_CUSTOM_NAMES = 0b00000001


@dataclass(frozen=True)
class SplitCachedResponse:
    """A cached query response with the `results` segment kept as raw, unparsed JSON bytes."""

    header: dict
    results_bytes: Optional[bytes]
    """Raw JSON bytes of the `results` field; None means `header` is the full legacy response."""
    results_have_custom_names: bool = False
    """Whether any series/step in results carries a non-null custom_name (so a cache hit may need patching)."""


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


def split_cached_response_bytes(cached_response_bytes: bytes) -> SplitCachedResponse:
    serializer = OrjsonJsonSerializer({})
    if not cached_response_bytes.startswith(QUERY_CACHE_SPLIT_MAGIC):
        return SplitCachedResponse(header=serializer.loads(cached_response_bytes), results_bytes=None)
    offset = len(QUERY_CACHE_SPLIT_MAGIC)
    flags = cached_response_bytes[offset]
    header_length = int.from_bytes(cached_response_bytes[offset + 1 : offset + 5], "big")
    header_start = offset + 5
    header = serializer.loads(cached_response_bytes[header_start : header_start + header_length])
    return SplitCachedResponse(
        header=header,
        results_bytes=cached_response_bytes[header_start + header_length :],
        results_have_custom_names=bool(flags & _SPLIT_FLAG_CUSTOM_NAMES),
    )


def fetch_split_cached_response_by_key(cache_key: str, team_id: int) -> Optional[SplitCachedResponse]:
    query_cache = get_query_cache()
    try:
        cached_response_bytes = query_cache.get(cache_key)
    except Exception:
        logger.warning("query_cache_read_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        try:
            query_cache.delete(cache_key)
        except Exception:
            pass
        return None

    if not cached_response_bytes:
        return None

    try:
        return split_cached_response_bytes(cached_response_bytes)
    except Exception:
        logger.exception(
            "query_cache_deserialize_error",
            cache_key=cache_key,
            team_id=team_id,
            exc_info=True,
        )
        return None


def fetch_cached_response_by_key(cache_key: str, team_id: int) -> Optional[dict]:
    split = fetch_split_cached_response_by_key(cache_key, team_id)
    if split is None:
        return None
    if split.results_bytes is None:
        return split.header
    try:
        split.header["results"] = OrjsonJsonSerializer({}).loads(split.results_bytes)
    except Exception:
        logger.exception("query_cache_deserialize_error", cache_key=cache_key, team_id=team_id, exc_info=True)
        return None
    return split.header


@dataclass(frozen=True)
class InsightResult:
    result: Optional[Any]
    last_refresh: Optional[datetime]
    cache_key: Optional[str]
    is_cached: bool
    timezone: Optional[str]
    has_more: Optional[bool] = None
    next_allowed_client_refresh: Optional[datetime] = None
    cache_target_age: Optional[datetime] = None
    timings: Optional[list[QueryTiming]] = None
    columns: Optional[list] = None
    query_status: Optional[Any] = None
    hogql: Optional[str] = None
    types: Optional[list] = None
    # A ResolvedDateRangeResponse-shaped dict — the field carries model_dump output
    resolved_date_range: Optional[dict] = None


@dataclass(frozen=True)
class NothingInCacheResult(InsightResult):
    result: Optional[Any] = None
    last_refresh: Optional[datetime] = None
    cache_key: Optional[str] = None
    is_cached: bool = False
    timezone: Optional[str] = None
    next_allowed_client_refresh: Optional[datetime] = None
    columns: Optional[list] = None
