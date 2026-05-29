from posthog.schema import ProductIntentContext, ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.utils import get_safe_cache, safe_cache_set

PROMOTED_PRODUCT_INTENT_CACHE_TTL_SECONDS = 60 * 60 * 24

_VALID_PRODUCT_KEYS: frozenset[str] = frozenset(p.value for p in ProductKey)

# Onboarding intent is by definition early-lifecycle — bound the lookback so
# ClickHouse can prune partitions on teams with long histories but no such event.
_PROMOTED_PRODUCT_INTENT_LOOKBACK_DAYS = 365

_PROMOTED_PRODUCT_INTENT_QUERY = f"""
SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, 'product_key'), ''), 'null'), '^"|"$', '') AS product_key
FROM events
WHERE team_id = %(team_id)s
  AND timestamp >= now() - INTERVAL {_PROMOTED_PRODUCT_INTENT_LOOKBACK_DAYS} DAY
  AND event = 'user showed product intent'
  AND replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, 'intent_context'), ''), 'null'), '^"|"$', '') = %(intent_context)s
ORDER BY timestamp DESC
LIMIT 1
"""


def _cache_key(team_id: int) -> str:
    return f"promoted_product_intent:{team_id}"


def _fetch_from_clickhouse(team_id: int) -> str | None:
    rows = sync_execute(
        _PROMOTED_PRODUCT_INTENT_QUERY,
        {
            "team_id": team_id,
            "intent_context": ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY.value,
        },
    )
    if not rows:
        return None
    value = rows[0][0]
    if not value or value not in _VALID_PRODUCT_KEYS:
        return None
    return value


def get_promoted_product_intent(team_id: int) -> str | None:
    """Return the team's most recent primary onboarding product intent, or None.

    Backs the experimental sidebar 'Promoted product' entry. Cached for 24h per team
    because the underlying value rarely changes after onboarding completes; the worst
    case on a stale cache is one wrong sidebar entry until the next TTL boundary.
    """
    cache_key = _cache_key(team_id)
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached or None
    result = _fetch_from_clickhouse(team_id)
    safe_cache_set(cache_key, result or "", timeout=PROMOTED_PRODUCT_INTENT_CACHE_TTL_SECONDS)
    return result
