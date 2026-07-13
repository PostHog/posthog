# Finding failing traces — queries

Concrete queries for each strategy in Step 2. Property names (`$ai_is_error`, `$ai_input_tokens`, …) are
the standard AI event properties; confirm the exact ones for this project with `read-data-schema`, and
see `exploring-llm-traces/references/events-and-properties.md` for the full schema and the `events` vs
`ai_events` split (heavy content like `$ai_input` / `$ai_output_choices` lives on `ai_events`).

## Discover the trace taxonomy

When the user isn't sure how their traffic splits, find the use cases before scoping to one:

```sql
-- By trace-id prefix convention (many apps namespace trace ids like "support:", "summarize:")
SELECT splitByChar(':', coalesce(properties.$ai_trace_id, ''))[1] AS kind, count() AS n
FROM events
WHERE event = '$ai_generation' AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY kind ORDER BY n DESC
```

Or group by whatever feature property the app sets (`ai_product`, `agent_mode`, a custom tag). Then scope
every query below to one slice.

## Code errors

The cheap first sweep. Group the messages to see the error classes:

```sql
SELECT properties.$ai_error AS error, count() AS n
FROM events
WHERE event = '$ai_generation' AND properties.$ai_is_error = 'true'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY error ORDER BY n DESC
```

Remember this only catches exceptions/API failures. A trace can succeed (no `$ai_is_error`) and still be
wrong — those silent failures need the other strategies.

## Metric outliers

Anomalies cluster around failures. Sort by a metric and read both extremes:

```sql
SELECT properties.$ai_trace_id AS trace_id,
       properties.$ai_input_tokens AS in_tok,
       properties.$ai_output_tokens AS out_tok,
       properties.$ai_latency AS latency,
       properties.$ai_total_cost_usd AS cost
FROM events
WHERE event = '$ai_generation' AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY out_tok DESC      -- also try in_tok, latency, cost; and ASC for truncation / empty outputs
LIMIT 25
```

What the extremes tend to mean: huge output = runaway/repetition; tiny output = truncation or refusal;
huge input = context bloat or a stuffed prompt; high latency/cost = inefficiency or a loop. Open the
interesting ones with `query-llm-trace`.

## Manual review of a stratified batch

Pull a mixed batch (slices and outcomes, not all errors) and read each candidate end to end:

```json
posthog:query-llm-traces-list
{ "dateRange": { "date_from": "-7d" }, "filterTestAccounts": true }
```

Then `query-llm-trace` on each. Reading ~20–30 across a use case usually surfaces the main modes.

## Existing-eval spikes

A jump in an existing eval's failures often exposes a new problem. Summarize the failures, then confirm
the spike with a daily count:

```json
posthog:llma-evaluation-list { "enabled": true }
posthog:llma-evaluation-summary-create { "evaluation_id": "<uuid>", "filter": "fail" }
```

```sql
SELECT toDate(timestamp) AS day, count() AS fails
FROM events
WHERE event = '$ai_evaluation' AND properties.$ai_evaluation_id = '<uuid>'
    AND properties.$ai_evaluation_result = false AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day ORDER BY day
```

`exploring-llm-evaluations` covers reading eval results in depth.

## Counting failure modes

After open-noting and grouping (Step 3), a quick frequency count over the traces you tagged makes the
ranking concrete — e.g. tally by a label you wrote into a scratch list, or, when the mode maps to a
property, count it directly:

```sql
SELECT properties.$ai_model AS model, count() AS n
FROM events
WHERE event = '$ai_generation' AND properties.$ai_is_error = 'true'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY model ORDER BY n DESC
```
