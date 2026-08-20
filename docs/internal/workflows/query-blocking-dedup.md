# Blocking query deduplication

When one request is already computing a query, other blocking requests for the same cache key wait for its cached result instead of running the query again. This covers concurrent refreshes of one insight, repeated identical API queries, and a user's blocking refresh racing an async or warming run of the same query, since async workers compute through the same code path.

## Mechanism

- A run about to compute claims `posthog:query_claim:{cache_key}` in the query cache Redis: set-if-absent, value is the run's id, TTL `CLAIM_TTL_SECONDS` (30s).
- A daemon thread in the claiming process extends the TTL of that process's claims every `CLAIM_REFRESH_INTERVAL_SECONDS` (5s), via a compare-then-extend script that never revives a claim another run took over. If the process dies, the thread dies with it and the claim expires within 30s.
- A run that loses the claim polls every `WAIT_POLL_INTERVAL_SECONDS` (0.3s): a new cached result means join it and serve it as a cache hit; the claim disappearing without a result (the holder errored or died) means try to claim and compute; `QUERY_BLOCKING_DEDUP_MAX_WAIT_SECONDS` (env, default 90s) elapsing means compute anyway.
- Release is compare-then-delete, so a run whose claim expired mid-computation cannot delete its successor's claim.

Every failure direction degrades to computing the query, the behavior without deduplication: Redis unreachable grants claims without storing them, a dead holder frees its claim by TTL, and an unreadable joined result falls back to computing.

Excluded: exports (they never write the cache, so there is no result to share) and runners whose `requires_fresh_calculation()` is true.

## Operating it

- `QUERY_BLOCKING_DEDUP_ENABLED` is an instance setting (editable on `/instance/settings`, via its API, or in Django admin), seeded from the env var of the same name and read on a 60s cache, so flipping it applies fleet-wide within about a minute with no restart. Default off.
- Metrics: `posthog_query_dedup_wait_total` and `posthog_query_dedup_wait_seconds`, labeled by outcome (`result_ready` joins, `claim_released` takeovers after an error or death, `timed_out` deadline hits). A high `timed_out` rate means legitimate long queries are being waited on; raise the max wait or accept the duplicate computes.

Code: `posthog/query_cache/inflight.py`, wired around blocking execution in `posthog/hogql_queries/query_runner.py`.
