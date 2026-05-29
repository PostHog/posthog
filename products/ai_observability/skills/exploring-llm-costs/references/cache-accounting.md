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

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    if(properties.$ai_cache_reporting_exclusive = 'true',
       sum(toInt(properties.$ai_cache_read_input_tokens))
         / nullIf(sum(toInt(properties.$ai_input_tokens))
                + sum(toInt(properties.$ai_cache_read_input_tokens))
                + sum(toInt(properties.$ai_cache_creation_input_tokens)), 0),
       sum(toInt(properties.$ai_cache_read_input_tokens))
         / nullIf(sum(toInt(properties.$ai_input_tokens)), 0)
    ) AS cache_hit_rate
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY model, properties.$ai_cache_reporting_exclusive
```

The same provider-aware `if(...)` formula is what powers `cache_hit_rate`
in the [breakdown patterns](./breakdown-patterns.md) "input vs output vs
cache economics" recipe.
