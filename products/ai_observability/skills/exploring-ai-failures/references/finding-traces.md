# Finding failing traces — queries

Concrete queries for each strategy in Step 2. Property names (`$ai_is_error`, `$ai_input_tokens`, …) are
the standard AI event properties; confirm the exact ones for this project with `read-data-schema`.

## Contents

- [Where heavy content lives: `events` vs `ai_events`](#where-heavy-content-lives-events-vs-ai_events)
- [Discover the trace taxonomy](#discover-the-trace-taxonomy)
- [Code errors](#code-errors)
- [Metric outliers](#metric-outliers)
- [Manual review of a stratified batch](#manual-review-of-a-stratified-batch)
- [Existing-eval spikes](#existing-eval-spikes)
- [Counting failure modes](#counting-failure-modes)

## Where heavy content lives: `events` vs `ai_events`

The `events` table keeps only lightweight metadata: token counts, costs, model, provider,
`$ai_trace_id`, latency, and error flags. All queries below use it. The heavy content is **not on
`events`**. It lives as native columns on a separate table, `posthog.ai_events`:

| Heavy content  | `events` property    | `ai_events` column |
| -------------- | -------------------- | ------------------ |
| Input messages | `$ai_input`          | `input`            |
| Output         | `$ai_output`         | `output`           |
| Output choices | `$ai_output_choices` | `output_choices`   |
| Input state    | `$ai_input_state`    | `input_state`      |
| Output state   | `$ai_output_state`   | `output_state`     |
| Tools          | `$ai_tools`          | `tools`            |

`query-llm-trace` and `query-llm-traces-list` read `posthog.ai_events` for you, so use them to read
traces. Use SQL on `posthog.ai_events` only for batch analysis. `trace_id` is its access path, not
`timestamp`, so filter `events` first to get trace IDs, then fetch the content by `trace_id`:

```sql
WITH matching_traces AS (
    SELECT DISTINCT properties.$ai_trace_id AS trace_id
    FROM events
    WHERE event = '$ai_generation' AND timestamp >= now() - INTERVAL 7 DAY
)
SELECT a.trace_id, a.span_id, a.model, a.input, a.output_choices
FROM posthog.ai_events AS a
WHERE a.trace_id IN (SELECT trace_id FROM matching_traces)
ORDER BY a.trace_id, a.timestamp
```

`posthog.ai_events` drops rows after the retention period (30 days by default), so older traces have
no content.

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

Then read each with `query-llm-trace`. Its one required argument is `traceId`, and the value to pass is
the trace's `id` from the list:

```json
posthog:query-llm-trace
{ "traceId": "<id from a query-llm-traces-list result>" }
```

Reading ~20–30 across a use case usually surfaces the main modes.

## Existing-eval spikes

A jump in an existing eval's failures often exposes a new problem. Find the eval, then confirm the spike
with a daily count and read the failing runs:

```json
posthog:llma-evaluation-list { "enabled": true }
```

```sql
SELECT toDate(timestamp) AS day, count() AS fails
FROM events
WHERE event = '$ai_evaluation' AND properties.$ai_evaluation_id = '<uuid>'
    AND (<fail predicate>) AND (isNull(properties.$ai_evaluation_skipped) OR properties.$ai_evaluation_skipped != 'true')
    AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != 'false')
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day ORDER BY day
```

Build `<fail predicate>` from the eval's output type and config, as in the fail predicate table in
`exploring-llm-evaluations`. `$ai_evaluation_result = 'false'` only fits a pass/fail eval that is not a detector.

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
