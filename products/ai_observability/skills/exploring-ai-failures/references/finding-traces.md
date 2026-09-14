# Finding failing traces — queries

Concrete queries for each strategy in Step 2. Property names (`$ai_is_error`, `$ai_input_tokens`, …) are
the standard AI event properties; confirm the exact ones for this project with `read-data-schema`, and
see `exploring-llm-traces/references/events-and-properties.md` for the full schema and the `events` vs
`ai_events` split (heavy content like `$ai_input` / `$ai_output_choices` lives on `ai_events`).

## Discover the trace taxonomy

When the user isn't sure how their traffic splits, find the use cases before scoping to one.
Apps label their traffic differently, and many label almost none of it.
So measure what this project sets before you group by it.

These queries count every event, including internal and test traffic, and `execute-sql` takes no
test-account filter. The review batch below drops test accounts, so the two populations differ. Confirm
a label you picked here with one filtered `query-llm-traces-list` call before you scope on it.

### 1. Trace names

`$ai_span_name` on `$ai_trace` events names the whole trace, which is the closest thing to a use case.
(`$ai_trace_name` is the older name for the same thing, kept for older data.)

```sql
SELECT coalesce(name, '(not set)') AS kind, count() AS traces
FROM (
    SELECT
        toString(properties.$ai_trace_id) AS trace_id,
        ifNull(
            argMinIf(ifNull(nullIf(toString(properties.$ai_span_name), ''),
                            nullIf(toString(properties.$ai_trace_name), '')),
                     timestamp, event = '$ai_trace'),
            argMin(ifNull(nullIf(toString(properties.$ai_span_name), ''),
                          nullIf(toString(properties.$ai_trace_name), '')), timestamp)
        ) AS name
    FROM events
    WHERE event IN ('$ai_trace', '$ai_span', '$ai_generation', '$ai_embedding',
                    '$ai_metric', '$ai_feedback')
        AND timestamp >= now() - INTERVAL 7 DAY
        AND notEmpty(toString(properties.$ai_trace_id))
    GROUP BY trace_id
)
GROUP BY kind ORDER BY traces DESC
```

The root `$ai_trace` event is emitted last, so a run still going or one that crashed partway has child
events but no root. This counts every trace and falls back to a child event's name, the way the traces
list does. Group on `$ai_trace` alone and those runs vanish, which hides the failures you came to find.

### 2. App-set tags

Many apps tag the traffic themselves, with `$ai_product`, `feature`, `agent_mode`, `$ai_agent_name`, or a
team-specific property. The tag can sit on the generation, on the root `$ai_trace` event, or on both. Run
`read-data-schema` on both events to see what this project has, then measure coverage of the
generation-level candidates together:

```sql
SELECT count() AS generations,
       round(100 * countIf(isNotNull(nullIf(toString(properties.$ai_product), '')))
             / count(), 1) AS pct_ai_product,
       round(100 * countIf(isNotNull(nullIf(toString(properties.$ai_span_name), '')))
             / count(), 1) AS pct_span_name,
       round(100 * countIf(isNotNull(nullIf(toString(properties.$ai_agent_name), '')))
             / count(), 1) AS pct_agent_name
FROM events
WHERE event = '$ai_generation' AND timestamp >= now() - INTERVAL 7 DAY
```

Each count reads an empty tag as unset, so a property the app sets to `''` does not look covered. Use the
same expression for any other candidate you add.

These percentages count generations, not traces. One agentic trace emits many generations, so it
outweighs many single-shot traces, and a trace whose generations carry several agent names lands in
several buckets. Use the split to rank the candidates, not to size the use cases.

A candidate you found on `$ai_trace` needs the trace-level measure instead. Count the traces that carry
it against every trace, so a run whose root event never arrived stays in the denominator:

```sql
SELECT countDistinct(toString(properties.$ai_trace_id)) AS traces,
       countDistinctIf(toString(properties.$ai_trace_id),
                       notEmpty(toString(properties.<candidate>))) AS with_tag
FROM events
WHERE event IN ('$ai_trace', '$ai_span', '$ai_generation', '$ai_embedding',
                '$ai_metric', '$ai_feedback')
    AND timestamp >= now() - INTERVAL 7 DAY
    AND notEmpty(toString(properties.$ai_trace_id))
```

At equal coverage, prefer the trace-level tag, because it already gives one value per trace.

Group by the best-covered one, and keep the unset rows visible so you see how much traffic it misses:

```sql
SELECT coalesce(nullIf(toString(properties.<best-covered property>), ''), '(not set)') AS kind,
       count() AS n
FROM events
WHERE event = '$ai_generation' AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY kind ORDER BY n DESC
```

Group a trace-level tag the way rung 1 groups the name: resolve one value per trace first, then count
the traces.

### 3. Trace-id prefix

A few apps namespace trace ids like `support:` or `summarize:`. Most SDKs generate an opaque UUID per
trace instead, so count the prefixes before you split on them:

```sql
SELECT countDistinctIf(toString(properties.$ai_trace_id),
                       notEmpty(toString(properties.$ai_trace_id))) AS traces,
       countDistinctIf(toString(properties.$ai_trace_id),
                       position(toString(properties.$ai_trace_id), ':') > 0) AS with_prefix
FROM events
WHERE event = '$ai_generation' AND timestamp >= now() - INTERVAL 7 DAY
```

A trace id is one value per trace, so count traces here rather than generation rows. Generations carrying
no trace id fall out of both counts, because they cannot carry a prefix either. Split on
`splitByChar(':', toString(properties.$ai_trace_id))[1]` only when `with_prefix` covers most of `traces`.

### 4. Read and name

When nothing above discriminates, pull a random sample (below), read it, and name the use cases from
what the traces do. This is slower, and it always works.

> **Reject a result that names nothing.** Three shapes all mean "this label does not split the traffic":
> one huge `(not set)` bucket, because the app never sets the property; one bucket per trace, because the
> value is an opaque id; and one generic bucket, because the value is a framework default such as
> `LangGraph` or `RunnableSequence`. None of them is a taxonomy. Move down the ladder rather than scope
> on one, because a category that mixes use cases blurs the failure modes you are trying to separate.

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

Pull a mixed batch (slices and outcomes, not all errors) and read each candidate end to end. The list
returns the newest traces first, so ask for a random order. Otherwise a recent batch job, demo, or load
test fills the batch, and you read one use case instead of a spread.

When a label from Step 1 discriminates, run the request once per slice so each slice gets its own quota:

```json
posthog:query-llm-traces-list
{ "dateRange": { "date_from": "-7d" }, "filterTestAccounts": true, "randomOrder": true, "limit": 10,
  "properties": [{ "key": "$ai_span_name", "type": "event", "operator": "exact", "value": ["<slice>"] }] }
```

Run one more pass with `$ai_is_error` set to `"true"` so failed traces reach the batch, then drop the
duplicate trace ids. When no label discriminates, take one random sample across all the traffic instead:

```json
posthog:query-llm-traces-list
{ "dateRange": { "date_from": "-7d" }, "filterTestAccounts": true, "randomOrder": true, "limit": 30 }
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
