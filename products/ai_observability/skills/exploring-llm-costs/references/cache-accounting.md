# Cache token accounting (exclusive vs inclusive)

Providers report cache tokens two ways, and the cache-hit-rate math
changes accordingly:

- **Exclusive** — `$ai_input_tokens` does **not** include cache tokens.
  Total input volume is `input_tokens + cache_read + cache_creation`.
  Anthropic currently reports this way on most SDKs.
- **Inclusive** — `$ai_input_tokens` already includes cache tokens.
  OpenAI and most others currently report this way.

Don't hardcode provider behavior — it varies by SDK and by SDK version,
and providers can change their own reporting style over time. Instead,
trust the per-event flag `$ai_cache_reporting_exclusive` (boolean).
Ingestion writes it when it calculates the event's cost, and callers can
set it explicitly when manually capturing.

The flag is often missing. Events whose cost arrives precomputed
(`$ai_cost_model_source = 'passthrough'`) skip that step, so they carry no
flag. For those, apply the same fallback ingestion uses: an event is
exclusive when `input_tokens < cache_read + cache_creation`, since an
inclusive count can never be smaller than its cache tokens.

## Cache-hit rate, resolved per event

Resolve the reporting style on each event, then aggregate. Picking one
style per group (`any(flag)`, or treating a missing flag as inclusive)
applies the wrong denominator to part of the group and can push the rate
above 1.

```sql
posthog:execute-sql
SELECT
    model,
    round(sum(cache_read) / nullIf(sum(if(exclusive, input + cache_read + cache_write, input)), 0), 3) AS cache_hit_rate,
    countIf(flag_missing) AS calls_with_inferred_flag,
    count() AS calls
FROM (
    SELECT
        properties.$ai_model AS model,
        ifNull(toInt(properties.$ai_input_tokens), 0) AS input,
        ifNull(toInt(properties.$ai_cache_read_input_tokens), 0) AS cache_read,
        ifNull(toInt(properties.$ai_cache_creation_input_tokens), 0) AS cache_write,
        properties.$ai_cache_reporting_exclusive IS NULL AS flag_missing,
        ifNull(properties.$ai_cache_reporting_exclusive, input < cache_read + cache_write) AS exclusive
    FROM events
    WHERE event = '$ai_generation'
        AND timestamp >= now() - INTERVAL 30 DAY
)
GROUP BY model
```

The flag is a boolean, so compare it as one (`IS NULL`, `ifNull(...)`),
not against the string `'true'`.

The inferred fallback is a lower bound on exclusivity: an exclusive event
whose fresh input outweighs its cache tokens reads as inclusive, which
overstates its rate. When `calls_with_inferred_flag` is a large share of
`calls`, say the rate is partly inferred.

The [breakdown patterns](./breakdown-patterns.md) "input vs output vs
cache economics" recipe and the
[regression debugging](./regression-debugging.md) cache step use this
same per-event resolution.
