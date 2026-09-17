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
trust the per-event flag: ingestion auto-detects and writes the resolved
value to `$ai_cache_reporting_exclusive` (boolean) on every
`$ai_generation`. Callers can also override with
`$ai_cache_reporting_exclusive: true|false` when manually capturing.

## Cache-hit rate, branching on the per-event flag

The flag is per event, so it must be in the `GROUP BY`. A model can mix
exclusive, inclusive and unset events on the same day, and the flag is often
unset. Never collapse the group with `any()` — that picks one event's flag and
applies its formula to every event in the group, which can report a rate above
1. Keep the unset events in their own row with no rate.

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    multiIf(
        properties.$ai_cache_reporting_exclusive = 'true', 'exclusive',
        properties.$ai_cache_reporting_exclusive = 'false', 'inclusive',
        'unavailable'
    ) AS cache_reporting,
    round(
        multiIf(
            cache_reporting = 'exclusive',
            sum(toInt(properties.$ai_cache_read_input_tokens))
                / nullIf(sum(toInt(properties.$ai_input_tokens))
                       + sum(toInt(properties.$ai_cache_read_input_tokens))
                       + sum(toInt(properties.$ai_cache_creation_input_tokens)), 0),
            cache_reporting = 'inclusive',
            sum(toInt(properties.$ai_cache_read_input_tokens))
                / nullIf(sum(toInt(properties.$ai_input_tokens)), 0),
            NULL
        ), 3
    ) AS cache_hit_rate,
    sum(toInt(properties.$ai_input_tokens)) AS input_tokens,
    sum(toInt(properties.$ai_cache_read_input_tokens)) AS cache_read_tokens
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY model, cache_reporting
```

A `cache_reporting = 'unavailable'` row has no valid denominator, so
`cache_hit_rate` is null there. Report it as unavailable and read the token
columns instead of guessing a formula.

The same flag-grouped formula powers `cache_hit_rate` in the [breakdown
patterns](./breakdown-patterns.md) "input vs output vs cache economics" recipe
and in [regression debugging](./regression-debugging.md) step 4.
