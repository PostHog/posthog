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

The flag is often missing. Ingestion writes it only when it calculates
the cost, so events with a precomputed (`passthrough`) cost, an unknown
model, or no input token count carry no flag. For those, apply the same
fallback ingestion uses: Anthropic-style events (provider `anthropic`, or a
model name with `anthropic` or starting with `claude`, except through the
Vercel AI Gateway) are exclusive.

Every event is also exclusive when `input_tokens < cache_read +
cache_creation`, since an inclusive count can never be smaller than its
cache tokens. This check also corrects a flag set to `false` by mistake,
and it keeps the rate at or below 1.

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
        lower(ifNull(properties.$ai_provider, '')) AS provider,
        properties.$ai_cache_reporting_exclusive IS NULL AS flag_missing,
        (provider = 'anthropic'
            OR positionCaseInsensitive(ifNull(properties.$ai_model, ''), 'anthropic') > 0
            OR startsWith(lower(ifNull(properties.$ai_model, '')), 'claude'))
            AND NOT (provider = 'gateway' AND lower(ifNull(properties.$ai_framework, '')) = 'vercel') AS anthropic_style,
        if(flag_missing, anthropic_style, toString(properties.$ai_cache_reporting_exclusive) = 'true')
            OR input < cache_read + cache_write AS exclusive
    FROM events
    WHERE event = '$ai_generation'
        AND timestamp >= now() - INTERVAL 30 DAY
)
GROUP BY model
```

Compare the flag through `toString(...) = 'true'` behind an `IS NULL`
check. Its type depends on the project's property definition (boolean or
string), and `toString` of a missing value returns `''`, not null.

The inferred fallback can still miss: an exclusive event from another
provider, whose fresh input outweighs its cache tokens, reads as
inclusive, which overstates its rate. When `calls_with_inferred_flag` is a
large share of `calls`, say the rate is partly inferred.

The [breakdown patterns](./breakdown-patterns.md) "input vs output vs
cache economics" recipe and the
[regression debugging](./regression-debugging.md) cache step use this
same per-event resolution.
