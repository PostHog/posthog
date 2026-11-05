# Debugging a cost regression

"Our LLM bill jumped — why?" is almost always one of: more calls, bigger
prompts, a new model, or a change in cache-hit rate. Work through them in order.

## Step 1 — Confirm and scope the regression

```sql
posthog:execute-sql
SELECT
    toDate(timestamp) AS day,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd,
    count() AS calls,
    round(sum(toFloat(properties.$ai_total_cost_usd)) / count(), 6) AS avg_cost_per_call
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 60 DAY
GROUP BY day
ORDER BY day
```

Compare `calls` vs `avg_cost_per_call` before and after the jump. If calls
doubled, it's volume; if cost-per-call rose, it's prompt size, model, or cache.

## Step 2 — Look for a model mix shift

```sql
posthog:execute-sql
SELECT
    toDate(timestamp) AS day,
    properties.$ai_model AS model,
    count() AS calls,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd,
    round(avg(toFloat(properties.$ai_total_cost_usd)), 6) AS avg_cost_per_call
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= now() - INTERVAL 60 DAY
GROUP BY day, model
ORDER BY day, model
```

A model appearing or disappearing around the jump is a strong signal. So is a
model taking a bigger share of `calls` or `cost_usd` after it, even when its
own `avg_cost_per_call` held steady.

## Step 3 — Look for prompt bloat

```sql
posthog:execute-sql
SELECT
    toDate(timestamp) AS day,
    properties.$ai_model AS model,
    round(avg(toInt(properties.$ai_input_tokens)), 1) AS avg_input_tokens,
    round(avg(toInt(properties.$ai_output_tokens)), 1) AS avg_output_tokens
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day, model
ORDER BY day, model
```

## Step 4 — Look for cache degradation

```sql
posthog:execute-sql
SELECT
    day,
    model,
    round(sum(cache_read) / nullIf(sum(if(exclusive, input + cache_read + cache_write, input)), 0), 3) AS cache_hit_rate,
    sum(input) AS input_tokens,
    sum(cache_read) AS cache_read_tokens,
    countIf(flag_missing) AS calls_with_inferred_flag,
    count() AS calls
FROM (
    SELECT
        toDate(timestamp) AS day,
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
GROUP BY day, model
ORDER BY day, model
```

A drop often follows a system-prompt change that invalidated the cached prefix.
The rate resolves the reporting style per event; see
[cache accounting](./cache-accounting.md) for why, and for how to read
`calls_with_inferred_flag`.

## Step 5 — Isolate the feature

Once you've identified the mechanism (more calls / bigger prompts / new model /
worse cache), group by the custom property that separates features (e.g.
`feature`, `workflow_name`) to find which surface is responsible. Then drill
into a representative trace via `posthog:query-llm-trace`.
