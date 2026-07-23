"""Who may be served stale, and for how long — and how a stale serve is marked.

The executor's `stale_while_revalidate_seconds` is the *serve* half of RFC 5861: a request that would
otherwise materialize inline gets its complete-but-stale rows back instantly instead of blocking. The
rule for *who* may take that grace is the same in every product, and getting it wrong is a data-freezing
bug rather than a slow query — a background refresher served its own stale rows persists them as a fresh
result and never recomputes, so nothing refreshes again. Hence one implementation, here, next to the
executor, instead of one per product.

Products supply the triggers of their own warmers; the CACHE_WARMUP feature tag is the primary,
product-agnostic gate. Callers that take the grace must have a revalidation path (a background refresher,
or an enqueue on `stale=True`), otherwise they serve stale until the grace runs out.

This module also owns the request-scoped *marker* for "this read was served stale". Products call
`mark_served_stale()` when an ensure comes back `stale=True`; the marker then feeds two surfaces:

- ClickHouse `system.query_log` (via the `precompute_stale` query tag), so stale-served reads can be
  compared against fresh ones without joining Prometheus.
- The API response (each runner stamps `preComputeStale` on its lazy responses from `was_served_stale()`),
  so the requester knows the data is stale and a background revalidation is on its way.

A lazy read that *fails after* marking (e.g. the compare period misses and the whole read falls back to
the live query) must call `clear_served_stale()` — the fallback response is fresh, and a lingering marker
would mislabel it on both surfaces.
"""

from posthog.clickhouse.query_tagging import Feature, clear_tag, get_query_tag_value, tag_queries

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


# The query tag marking a stale-served read. One name shared by every product so query_log analysis
# and response stamping never drift; it is a typed field on QueryTags.
SERVED_STALE_TAG = "precompute_stale"


def mark_served_stale() -> None:
    """Mark this request as served from stale precompute rows (call when an ensure returns `stale=True`)."""
    tag_queries(precompute_stale=True)


def clear_served_stale() -> None:
    """Unmark a stale serve after the lazy read failed and the caller falls back to a live query."""
    clear_tag(SERVED_STALE_TAG)


def was_served_stale() -> bool:
    """Whether any ensure in this request served stale rows. Runners stamp `preComputeStale` from this."""
    return bool(get_query_tag_value(SERVED_STALE_TAG))
