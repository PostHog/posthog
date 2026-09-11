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

Group by model on both sides of the jump. Replace `<jump_day>` with the day
Step 1 pointed at:

```sql
posthog:execute-sql
SELECT
    properties.$ai_model AS model,
    properties.$ai_provider AS provider,
    if(timestamp >= toDateTime('<jump_day>'), 'after', 'before') AS window,
    count() AS calls,
    round(count() / sum(count()) OVER (PARTITION BY window), 4) AS call_share,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd,
    round(
        sum(toFloat(properties.$ai_total_cost_usd))
            / nullIf(sum(sum(toFloat(properties.$ai_total_cost_usd))) OVER (PARTITION BY window), 0),
        4
    ) AS cost_share,
    round(avg(toFloat(properties.$ai_total_cost_usd)), 6) AS avg_cost_per_call
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding')
    AND timestamp >= toDateTime('<jump_day>') - INTERVAL 7 DAY
    AND timestamp < toDateTime('<jump_day>') + INTERVAL 7 DAY
GROUP BY model, provider, window
ORDER BY model, provider, window
```

Read the two rows per model together.
A model that appears only in `after`, or one that disappears, is a strong signal.
Then compare `call_share` and `cost_share` between the two windows.
A model that takes a larger share of the calls or the cost in `after` is a mix shift, even when its own `avg_cost_per_call` held steady.
Call it volume only when the shares held steady and the total call count moved.

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

Track the cache-hit rate per model per day. A drop often follows a
system-prompt change that invalidated the cached prefix:

```sql
posthog:execute-sql
SELECT
    toDate(timestamp) AS day,
    properties.$ai_model AS model,
    round(
        if(
            any(properties.$ai_cache_reporting_exclusive) = 'true',
            sum(toInt(properties.$ai_cache_read_input_tokens))
                / nullIf(sum(toInt(properties.$ai_input_tokens))
                       + sum(toInt(properties.$ai_cache_read_input_tokens))
                       + sum(toInt(properties.$ai_cache_creation_input_tokens)), 0),
            sum(toInt(properties.$ai_cache_read_input_tokens))
                / nullIf(sum(toInt(properties.$ai_input_tokens)), 0)
        ), 3
    ) AS cache_hit_rate,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day, model
ORDER BY day, model
```

The `if(...)` branches on the per-event `$ai_cache_reporting_exclusive` flag,
so the denominator is correct for both exclusive and inclusive providers. Never
branch on provider or model name.

A `cache_hit_rate` above 1 means the flag is unset on those events, so the
query took the inclusive path over exclusive data. Treat that number as
unusable. Read the cache-read, cache-write, and input token columns instead.

## Step 5 — Isolate the feature

Once you've identified the mechanism (more calls / bigger prompts / new model /
worse cache), group by the custom property that separates features (e.g.
`feature`, `workflow_name`) to find which surface is responsible. Then drill
into a representative trace via `posthog:query-llm-trace`.
