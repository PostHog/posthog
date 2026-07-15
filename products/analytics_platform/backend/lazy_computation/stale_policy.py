"""Who may be served stale, and for how long.

The executor's `stale_while_revalidate_seconds` is the *serve* half of RFC 5861: a request that would
otherwise materialize inline gets its complete-but-stale rows back instantly instead of blocking. The
rule for *who* may take that grace is the same in every product, and getting it wrong is a data-freezing
bug rather than a slow query — a background refresher served its own stale rows persists them as a fresh
result and never recomputes, so nothing refreshes again. Hence one implementation, here, next to the
executor, instead of one per product.

Products supply the triggers of their own warmers; the CACHE_WARMUP feature tag is the primary,
product-agnostic gate. Callers that take the grace must have a revalidation path (a background refresher,
or an enqueue on `stale=True`), otherwise they serve stale until the grace runs out.
"""

from posthog.clickhouse.query_tagging import Feature, get_query_tag_value

# Refreshers every product inherits. The generic insight cache warmer's CACHE_WARMUP feature tag does not
# always survive to the ensure call (lazy modules re-stamp feature=QUERY before ensuring), but its trigger
# does — without it, warmer runs get served stale and persist that into the insight cache as fresh.
SHARED_BACKGROUND_WARMING_TRIGGERS = frozenset({"warmingV2"})


def is_background_warming_request(extra_triggers: frozenset[str] = frozenset()) -> bool:
    """True when this request *is* a refresh mechanism rather than a consumer of one.

    `extra_triggers` are the calling product's own warmer triggers, unioned with the shared set. The
    feature tag is the primary gate: it classifies refreshers by category, including warmers the caller
    does not know by name.
    """
    if get_query_tag_value("feature") == Feature.CACHE_WARMUP:
        return True
    return get_query_tag_value("trigger") in (SHARED_BACKGROUND_WARMING_TRIGGERS | extra_triggers)


def resolve_stale_while_revalidate_seconds(
    grace_seconds: float,
    extra_triggers: frozenset[str] = frozenset(),
) -> float | None:
    """The serve-stale grace this request may take: None for refreshers, `grace_seconds` for user reads."""
    return None if is_background_warming_request(extra_triggers) else grace_seconds
