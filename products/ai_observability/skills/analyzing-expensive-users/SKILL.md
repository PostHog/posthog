---
name: analyzing-expensive-users
description: >
  Analyze the most expensive users in AI observability and explain why they cost so much.
  Use when the user asks about top spenders, expensive users, per-user LLM cost,
  user-level cost drivers, or patterns behind high AI observability spend.
---

# Analyzing expensive users

Use this skill when the user wants to understand the most expensive users in
AI observability. The job is not just to rank users by cost. The useful answer
explains what makes the top users expensive: volume, model choice, prompt size,
output size, cache behavior, retries/errors, trace type, feature or tenant
dimensions, and representative trace examples.

For general cost rollups, also use `exploring-llm-costs`. For reading
individual traces, also use `exploring-llm-traces`.

## Tools

| Tool                            | Purpose                                                            |
| ------------------------------- | ------------------------------------------------------------------ |
| `posthog:execute-sql`           | Rank users and compare their metrics against the project baseline  |
| `posthog:query-llm-traces-list` | Find high-cost traces for a specific user                          |
| `posthog:query-llm-trace`       | Read representative traces to explain what actually happened       |
| `posthog:read-data-schema`      | Discover custom event or person properties before grouping by them |
| `posthog:generate-app-url`      | Build region- and project-qualified links back to the UI           |

## Core rules

- **Start with a bounded time range.** If the user does not specify one, use the
  last 30 days and say so. If the user provides a link or existing filters,
  preserve the date range, test-account filter, and property filters.
- **Start from generated-call spend.** The per-user ranking query groups
  `$ai_generation` rows by `distinct_id`, with `traces`, `generations`,
  `errors`, `total_cost`, `first_seen`, and `last_seen`. This is the best
  first pass for finding expensive users.
- **For full spend by user, include embeddings deliberately.** Broader cost
  rollups should include `event IN ('$ai_generation', '$ai_embedding')`, but
  call out when the event set changes.
- **Filter trace-id defaults when interpreting users.** Some SDKs use
  `$ai_trace_id` as `distinct_id` when no user is set. For identified users,
  exclude `distinct_id = properties.$ai_trace_id` and flag how much spend
  becomes unattributed.
- **Do not guess custom dimensions.** Discover event and person properties
  before grouping by `feature`, `tenant_id`, `plan`, `workflow_name`, or similar
  customer-specific fields.
- **Read traces before explaining causality.** Aggregates identify suspects;
  representative traces show whether the user is expensive because of a real
  workflow, retries, loops, large context, tool-heavy generations, or other
  behavior.

## Workflow

### 1. Rank users by generated-call spend

Use this first when the question asks for the most expensive users:

```sql
posthog:execute-sql
SELECT
    distinct_id,
    argMax(email, timestamp) AS email,
    argMax(name, timestamp) AS name,
    countDistinctIf(ai_trace_id, notEmpty(ai_trace_id)) AS traces,
    count() AS generations,
    countIf(notEmpty(ai_error) OR ai_is_error = 'true') AS errors,
    round(sum(ai_total_cost_usd), 4) AS total_cost,
    round(avg(ai_total_cost_usd), 6) AS avg_cost_per_generation,
    sum(ai_input_tokens) AS input_tokens,
    sum(ai_output_tokens) AS output_tokens,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM (
    SELECT
        distinct_id,
        timestamp,
        toString(properties.$ai_trace_id) AS ai_trace_id,
        toFloat(properties.$ai_total_cost_usd) AS ai_total_cost_usd,
        toString(properties.$ai_error) AS ai_error,
        toString(properties.$ai_is_error) AS ai_is_error,
        toInt(properties.$ai_input_tokens) AS ai_input_tokens,
        toInt(properties.$ai_output_tokens) AS ai_output_tokens,
        toString(person.properties.email) AS email,
        toString(person.properties.name) AS name
    FROM events
    WHERE event = '$ai_generation'
        AND timestamp >= now() - INTERVAL 30 DAY
)
GROUP BY distinct_id
ORDER BY total_cost DESC
LIMIT 25
```

If the user is asking for identified users, add this
inside the inner `WHERE` clause:

```sql
AND (
    properties.$ai_trace_id IS NULL
    OR distinct_id != properties.$ai_trace_id
)
```

Project only the explicit label columns you need, such as `email` and `name`.
Never select the raw `person.properties` object or a tuple containing it: it
serializes the full property blob into the result and leaks personal data far
beyond a label. If a user has no email or name, fall back to `distinct_id`.

### 2. Establish the baseline

The top user is only meaningful relative to everyone else. Run a per-user
baseline so you can say whether a user is expensive because they have more
generations, more traces, higher cost per generation, longer prompts, longer
outputs, or a higher error rate.

```sql
posthog:execute-sql
WITH per_user AS (
    SELECT
        distinct_id,
        count() AS generations,
        countDistinctIf(toString(properties.$ai_trace_id), notEmpty(toString(properties.$ai_trace_id))) AS traces,
        countIf(notEmpty(toString(properties.$ai_error)) OR toString(properties.$ai_is_error) = 'true') AS errors,
        sum(toFloat(properties.$ai_total_cost_usd)) AS total_cost,
        avg(toFloat(properties.$ai_total_cost_usd)) AS avg_cost_per_generation,
        avg(toInt(properties.$ai_input_tokens)) AS avg_input_tokens,
        avg(toInt(properties.$ai_output_tokens)) AS avg_output_tokens
    FROM events
    WHERE event = '$ai_generation'
        AND timestamp >= now() - INTERVAL 30 DAY
    GROUP BY distinct_id
)
SELECT
    count() AS users,
    round(sum(total_cost), 4) AS total_cost,
    round(avg(total_cost), 4) AS avg_cost_per_user,
    round(quantile(0.5)(total_cost), 4) AS p50_user_cost,
    round(quantile(0.9)(total_cost), 4) AS p90_user_cost,
    round(quantile(0.99)(total_cost), 4) AS p99_user_cost,
    round(avg(avg_cost_per_generation), 6) AS avg_cost_per_generation,
    round(avg(avg_input_tokens), 0) AS avg_input_tokens,
    round(avg(avg_output_tokens), 0) AS avg_output_tokens,
    round(sum(errors) / nullIf(sum(generations), 0), 4) AS error_rate
FROM per_user
```

When reporting top users, include each user's share of total spend and how many
multiples above p50/p90 they are. That makes the skew obvious.

### 3. Decompose the top user's cost drivers

For each top user worth explaining, break their spend down by model and token
economics.

```sql
posthog:execute-sql
SELECT
    toString(properties.$ai_provider) AS provider,
    toString(properties.$ai_model) AS model,
    count() AS generations,
    countDistinctIf(toString(properties.$ai_trace_id), notEmpty(toString(properties.$ai_trace_id))) AS traces,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS total_cost,
    round(avg(toFloat(properties.$ai_total_cost_usd)), 6) AS avg_cost_per_generation,
    sum(toInt(properties.$ai_input_tokens)) AS input_tokens,
    sum(toInt(properties.$ai_output_tokens)) AS output_tokens,
    sum(toInt(properties.$ai_reasoning_tokens)) AS reasoning_tokens,
    sum(toInt(properties.$ai_cache_read_input_tokens)) AS cache_read_tokens,
    sum(toInt(properties.$ai_cache_creation_input_tokens)) AS cache_write_tokens,
    round(sum(toFloat(properties.$ai_input_cost_usd)), 4) AS input_cost,
    round(sum(toFloat(properties.$ai_output_cost_usd)), 4) AS output_cost,
    round(sum(toFloat(properties.$ai_request_cost_usd)), 4) AS request_cost,
    round(sum(toFloat(properties.$ai_web_search_cost_usd)), 4) AS web_search_cost,
    countIf(notEmpty(toString(properties.$ai_error)) OR toString(properties.$ai_is_error) = 'true') AS errors
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND distinct_id = '<distinct_id>'
GROUP BY provider, model
ORDER BY total_cost DESC
```

Interpret the result using this decision tree:

- **High generations, ordinary cost per generation** means volume is the driver.
- **High cost per generation, ordinary volume** means expensive models, long
  context, long outputs, reasoning tokens, web-search fees, or request fees are
  the driver.
- **High input tokens** usually points to context bloat, repeated conversation
  history, large retrieved documents, or missing truncation.
- **High output or reasoning tokens** points to verbose answers, chain-of-thought
  style reasoning models, missing output limits, or tool loops.
- **Low cache reuse with high repeated input** points to missed prompt caching.
  Use the cache formula from `exploring-llm-costs/references/cache-accounting.md`.
- **High errors or many high-cost traces** points to retries, failed tool calls,
  or loops. Read traces before saying which one.
- **High request or web-search cost** points to provider flat fees or tool-heavy
  generations, not token volume alone.

### 4. Compare the top user against everyone else

Run the same model or token breakdown for the whole project, then compare. Do
not rely on raw totals only. You want statements like "this user used the same
models as everyone else, but had 9x more generations" or "their volume was
normal, but 82% of spend went to a high-cost model that is rare elsewhere."

Useful comparisons:

- Top user's share of total project cost
- Top user's generations and traces versus p50/p90 user
- Average cost per generation versus project average
- Input tokens per generation versus project average
- Output or reasoning tokens per generation versus project average
- Error rate versus project average
- Model mix versus global model mix
- Cache-hit rate versus global cache-hit rate for the same model

### 5. Find the user's expensive traces

Use SQL for the ranked trace list, then read representative traces with
`posthog:query-llm-trace`.

```sql
posthog:execute-sql
SELECT
    toString(properties.$ai_trace_id) AS trace_id,
    count() AS generations,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS total_cost,
    round(avg(toFloat(properties.$ai_total_cost_usd)), 6) AS avg_cost_per_generation,
    sum(toInt(properties.$ai_input_tokens)) AS input_tokens,
    sum(toInt(properties.$ai_output_tokens)) AS output_tokens,
    countIf(notEmpty(toString(properties.$ai_error)) OR toString(properties.$ai_is_error) = 'true') AS errors,
    min(timestamp) AS started_at,
    max(timestamp) AS ended_at
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND distinct_id = '<distinct_id>'
    AND notEmpty(toString(properties.$ai_trace_id))
GROUP BY trace_id
ORDER BY total_cost DESC
LIMIT 10
```

Open at least the top 2-3 traces for the user:

```json
posthog:query-llm-trace
{
  "traceId": "<trace_id>",
  "dateRange": { "date_from": "-30d" }
}
```

Look for the first concrete pattern that explains the aggregate:

- repeated tool calls or retry loops
- large context windows or repeated retrieved documents
- long multi-turn sessions
- expensive model selected for ordinary tasks
- many small calls from the same workflow
- verbose outputs or unconstrained reasoning
- web-search or request-fee-heavy calls
- errors that still incurred model cost

### 6. Check custom dimensions when the aggregate is ambiguous

If the top user appears expensive but the model/token breakdown does not explain
why, discover custom event properties on `$ai_generation` and group by the
likely product dimensions. Common examples are `feature`, `tenant_id`,
`organization_id`, `workflow_name`, `agent`, `route`, or `environment`, but do
not guess.

1. Call `posthog:read-data-schema` with `kind: "event_properties"` and
   `event_name: "$ai_generation"`.
2. For promising fields, call `posthog:read-data-schema` with
   `kind: "event_property_values"` to confirm actual values.
3. Group the top user's cost by the discovered property.

```sql
posthog:execute-sql
SELECT
    toString(properties.<property_name>) AS dimension,
    count() AS generations,
    countDistinctIf(toString(properties.$ai_trace_id), notEmpty(toString(properties.$ai_trace_id))) AS traces,
    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS total_cost,
    round(avg(toFloat(properties.$ai_total_cost_usd)), 6) AS avg_cost_per_generation
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND distinct_id = '<distinct_id>'
    AND isNotNull(properties.<property_name>)
GROUP BY dimension
ORDER BY total_cost DESC
LIMIT 20
```

This is often the difference between "user 123 is expensive" and "their
contract-review workflow is expensive because every run feeds a 90k-token
document to the most costly model."

## Constructing UI links

Use `posthog:generate-app-url` for links. Do not hardcode the host because the
project may be in a different region.

- Traces list: `generate-app-url { "url": "/ai-observability/traces" }`
- Single trace: `generate-app-url { "url": "/ai-observability/traces/{id}", "params": { "id": "<trace_id>" } }`

For a single trace, append `?timestamp=<url_encoded_started_at>` when you have
the trace timestamp so the UI opens the right time window.

## Response shape

Lead with the answer, not the queries. A good response has:

1. **Top users** - ranked by total cost, with total cost, share of spend,
   generations, traces, average cost per generation, and error rate. Identify
   each user by a label only (email, name, or `distinct_id`). Do not print raw
   `person.properties` objects or other personal fields the user did not ask for.
2. **Why they are expensive** - one or two concrete drivers per user, compared
   against the baseline.
3. **Evidence** - model/token/cache/custom-dimension breakdowns plus linked
   example traces you read.
4. **Likely levers** - specific optimization ideas tied to the observed driver:
   reduce context, cap output, use a cheaper model for a workflow, improve
   caching, fix retry loops, or split a feature's traffic.
5. **Caveats** - whether the result includes embeddings, excludes trace-id
   defaults, or uses a different event set than the initial ranking.

Avoid generic advice. "Use cheaper models" is not useful unless the data shows
that model mix is the driver. "Reduce prompt size" is not useful unless input
tokens are high relative to the baseline.
