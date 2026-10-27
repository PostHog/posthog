import json
import datetime as dt
from typing import Any

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_async_client

from .constants import (
    REDIS_TTL_SECONDS,
    SALESFORCE_ACCOUNTS_CACHE_KEY,
    SALESFORCE_ORG_MAPPINGS_CACHE_KEY,
    SALESFORCE_STRIPE_ENRICHMENT_WATERMARK_KEY,
)

_LIST_PIPELINE_BATCH = 5000  # Entries per RPUSH call during list population
_CHUNK_ACCOUNT_FIELDS = ("Id", "Website")


async def _store_json_list(cache_key: str, items: list[dict[str, Any]], ttl: int) -> None:
    """Each item is its own list entry, so a reader fetches one page with LRANGE instead of parsing the whole dataset."""
    redis_client = get_async_client()
    pipe = await redis_client.pipeline()
    pipe.delete(cache_key)

    for i in range(0, len(items), _LIST_PIPELINE_BATCH):
        batch = items[i : i + _LIST_PIPELINE_BATCH]
        pipe.rpush(cache_key, *[json.dumps(item, default=str) for item in batch])

    pipe.expire(cache_key, ttl)
    await pipe.execute()


async def _get_list_page(cache_key: str, offset: int, limit: int) -> list[Any] | None:
    """Return the raw entries of one page, an empty list past the end, or None when the key is missing."""
    redis_client = get_async_client()
    raw_items = await redis_client.lrange(cache_key, offset, offset + limit - 1)
    if raw_items:
        return raw_items

    # LRANGE returns nothing both when the key is missing and when the offset is
    # past the end of the list; LLEN tells those cases apart.
    total = await redis_client.llen(cache_key)
    if total and offset >= total:
        return []
    return None


async def _get_list_length(cache_key: str) -> int | None:
    try:
        redis_client = get_async_client()
        count = await redis_client.llen(cache_key)
        return count if count > 0 else None
    except Exception as e:
        capture_exception(e)
        return None


async def store_accounts_in_redis(
    accounts_data: list[dict[str, Any]],
    ttl: int = REDIS_TTL_SECONDS,
) -> None:
    accounts = [{field: account[field] for field in _CHUNK_ACCOUNT_FIELDS} for account in accounts_data]
    await _store_json_list(SALESFORCE_ACCOUNTS_CACHE_KEY, accounts, ttl)


async def get_accounts_from_redis(offset: int = 0, limit: int = 1000) -> list[dict[str, Any]] | None:
    """Return one page of cached accounts, an empty list past the end, or None when the cache is missing."""
    raw_items = await _get_list_page(SALESFORCE_ACCOUNTS_CACHE_KEY, offset, limit)
    if raw_items is None:
        return None
    return [json.loads(item) for item in raw_items]


async def get_cached_accounts_count() -> int | None:
    return await _get_list_length(SALESFORCE_ACCOUNTS_CACHE_KEY)


async def store_org_mappings_in_redis(
    mappings_data: list[dict[str, Any]],
    ttl: int = REDIS_TTL_SECONDS,
) -> None:
    await _store_json_list(SALESFORCE_ORG_MAPPINGS_CACHE_KEY, mappings_data, ttl)


async def _lrange_json_or_none(key: str, start: int, end: int) -> list[dict[str, Any]] | None:
    """Fetch a range from a Redis List, returning None on cache miss or error."""
    try:
        redis_client = get_async_client()
        raw_items = await redis_client.lrange(key, start, end)

        if not raw_items:
            return None

        return [json.loads(item) for item in raw_items]

    except Exception as e:
        capture_exception(e)
        return None


class OrgMappingsCacheMissingError(Exception):
    """The org mappings cache key is absent or holds unreadable entries.

    Callers should rebuild the cache. Transient Redis errors deliberately do not
    map to this error — they propagate as-is so activity retry policies can
    absorb them instead of triggering a needless rebuild.
    """


async def get_org_mappings_page(offset: int = 0, limit: int = 10000) -> list[dict[str, Any]]:
    """Retrieve a page of org mappings via LRANGE — no decompression needed.

    Returns an empty list when ``offset`` is at or past the end of the cached
    list, meaning pagination is complete. Raises ``OrgMappingsCacheMissingError``
    when the key is missing or an entry cannot be parsed, so callers never
    mistake an expired cache for a completed run.
    """
    raw_items = await _get_list_page(SALESFORCE_ORG_MAPPINGS_CACHE_KEY, offset, limit)
    if raw_items is None:
        raise OrgMappingsCacheMissingError("org mappings cache key is missing")
    try:
        return [json.loads(item) for item in raw_items]
    except (TypeError, ValueError) as e:
        raise OrgMappingsCacheMissingError("org mappings cache entries are unreadable") from e


async def get_org_mappings_from_redis() -> list[dict[str, Any]] | None:
    """Retrieve all org mappings from Redis cache.

    Returns:
        List of mapping dictionaries, or None if cache miss/error
    """
    return await _lrange_json_or_none(SALESFORCE_ORG_MAPPINGS_CACHE_KEY, 0, -1)


async def get_cached_org_mappings_count() -> int | None:
    """Get the total count of cached org mappings via LLEN (O(1)).

    Returns:
        Total number of cached mappings, or None if key missing
    """
    return await _get_list_length(SALESFORCE_ORG_MAPPINGS_CACHE_KEY)


async def get_stripe_enrichment_watermark() -> tuple[dt.datetime, str] | None:
    """Read the high-water mark from the last successful stripe-enrichment run.

    Returns the keyset position ``(last_changed_at, posthog_organization_id)``
    of the last successfully processed row
    """
    redis_client = get_async_client()
    raw = await redis_client.get(SALESFORCE_STRIPE_ENRICHMENT_WATERMARK_KEY)
    if raw is None:
        return None
    value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    parsed = json.loads(value)
    return (
        dt.datetime.fromisoformat(parsed["last_changed_at"]),
        str(parsed["posthog_organization_id"]),
    )


async def set_stripe_enrichment_watermark(last_changed_at: dt.datetime, posthog_organization_id: str) -> None:
    """Persist the keyset high-water mark for the next incremental run.

    The key is intentionally not TTL'd so a missed run never silently degrades
    into a full resync — if the watermark is gone, it's gone on purpose.
    """
    payload = json.dumps(
        {
            "last_changed_at": last_changed_at.isoformat(),
            "posthog_organization_id": posthog_organization_id,
        }
    )
    redis_client = get_async_client()
    await redis_client.set(SALESFORCE_STRIPE_ENRICHMENT_WATERMARK_KEY, payload)
