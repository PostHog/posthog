Fetch a single LLM trace by its trace ID for deep inspection. Returns the trace and every nested event, with model parameters, costs, tool calls, and errors. Use after finding a trace via `query-llm-traces-list` to inspect the complete event tree.

By default the response returns the retained event properties, subject to response size limits. Set `detail` to `"summary"` for metadata alone when browsing a trace, with no prompts or outputs in it.

Use cases:

- Inspect the full input/output of each generation in a trace
- Debug a specific error trace found in the list
- Examine the agent's decision-making flow across spans
- Review tool calls and their results within a trace
- Analyze token usage and costs per generation

CRITICAL: This tool requires a `traceId`. Get the trace ID from `query-llm-traces-list` results first.

# Response shape

The response contains a single trace in JSON format with:

- `id` — the trace ID
- `traceName` — name of the trace (if set via SDK)
- `createdAt` — timestamp of the first event in the trace
- `distinctId` — the person's distinct ID
- `aiSessionId` — session ID grouping related traces (e.g., a conversation)
- `totalLatency` — total latency in seconds
- `inputTokens` / `outputTokens` — token counts across all generations
- `inputCost` / `outputCost` / `totalCost` — costs in USD
- `inputState` / `outputState` — JSON input/output state from the root `$ai_trace` event (e.g., conversation messages)
- `events` — **all** child events in the trace at every nesting depth (not just direct children), subject to response size limits. Each event has `properties`, holding the retained properties in full by default and metadata only under `detail: "summary"`.

Unlike `query-llm-traces-list`, this tool does NOT return `errorCount`, `isSupportTrace`, or `tools` — those are summary fields on the list tool only.

# Event types and their properties

Each event in `events` has an `event` field indicating its type. Key properties vary by type:

- **`$ai_generation`** / **`$ai_embedding`** — an LLM or embedding API call. Properties include `$ai_input` (input prompt JSON), `$ai_output_choices` (output message JSON), `$ai_model`, `$ai_provider`, `$ai_latency`, `$ai_input_tokens`, `$ai_output_tokens`, `$ai_input_cost_usd`, `$ai_output_cost_usd`, `$ai_total_cost_usd`, `$ai_tools_called`, `$ai_is_error`, `$ai_error`.
- **`$ai_span`** — a unit of work within a trace (e.g., a retrieval step, tool execution). Properties include `$ai_input_state`, `$ai_output_state`, `$ai_latency`, `$ai_span_name`, `$ai_parent_id`.
- **`$ai_metric`** — a named evaluation metric. Properties include `$ai_metric_name`, `$ai_metric_value`.
- **`$ai_feedback`** — user-provided feedback. Properties include `$ai_feedback_text`.

Note: `$ai_trace` events are NOT included in the `events` array — their data is surfaced via the trace-level `inputState`, `outputState`, and `traceName` fields.

# Tree structure (IDs and parent-child relationships)

Events in a trace form a tree. Each event carries three IDs that define its position:

- `$ai_trace_id` — present on every event, identifies which trace it belongs to (same as the trace's `id`)
- `$ai_span_id` (or `$ai_generation_id` for generations) — the event's own unique identifier
- `$ai_parent_id` — points to the parent event's `$ai_span_id`

To reconstruct the tree:

1. Events where `$ai_parent_id` equals `$ai_trace_id` are **root-level children** of the trace
2. Other events are children of the event whose `$ai_span_id` matches their `$ai_parent_id`
3. Group events by `$ai_parent_id` and walk from root children downward

Generations (`$ai_generation`) and embeddings (`$ai_embedding`) are always leaf nodes. Spans (`$ai_span`) can have children.

# Examples

## Fetch a trace by ID

```json
{
  "kind": "TraceQuery",
  "traceId": "c9222e05-8708-41b8-98ea-d4a21849e761"
}
```

## Fetch with a date range hint

If the trace is old, provide a date range to help the query find it efficiently:

```json
{
  "kind": "TraceQuery",
  "traceId": "c9222e05-8708-41b8-98ea-d4a21849e761",
  "dateRange": { "date_from": "-30d" }
}
```

# Detail level

`detail` controls how much of each event you get back.

- `"full"` (default) returns every retained property in full, bounded by the response size limit below.
- `"summary"` opts into trace fields, plus each event's `id`, `createdAt`, `event` type, and its navigation properties: `$ai_trace_id`, `$ai_span_id`, `$ai_generation_id`, `$ai_parent_id`, `$ai_span_name`, `$ai_model`, `$ai_provider`, `$ai_latency`, token counts, costs, `$ai_tools_called`, `$ai_is_error`, `$ai_http_status`, `$ai_metric_name`, and `$ai_metric_value`. Everything else is left out, not shortened: their names are listed in `_summaryOmittedKeys` beside the bag. A summarized trace carries `_detail: { "mode": "summary" }`.
- A summary carries no free text at all. Prompts, outputs, span states, `inputState` / `outputState`, `$ai_error`, and `$ai_feedback_text` all need `detail: "full"`. Use `$ai_is_error` and `$ai_http_status` to find the failed events in a summary, then read their messages at full detail.

For a cost or latency survey, request `detail: "summary"` — it carries no conversation content at all. Find the events that matter from their metadata, then re-run with `detail: "full"` when you need the text. Keep relevant date and property filters when requesting full detail.

# Withheld properties

Only `$ai_*` properties PostHog's taxonomy defines, plus `$ai_generation_id`, `$session_id`, `$lib`, and `$lib_version`, reach you. Every other event property, and every person property, is withheld whichever `detail` you ask for, and its name is listed in `_redactedKeys` beside the bag. `$ai_base_url` and `$ai_request_url` arrive without their query string.

A withheld property is unchanged in PostHog: it still works as a filter here, and you can read its value in the PostHog UI or with `execute-sql`.

# Response size

To protect the agent's context window, very large traces are compacted before they reach you. Long string values are truncated (with a `… [truncated N chars]` marker), oversized arrays and objects have their tail members dropped (`… [N more items omitted]` / an `_omittedKeys` count), and if a trace is still over the size limit, trailing events are dropped and a `_truncated` object reports how many events were omitted. When you see any of these markers, open the trace in PostHog for the full, untruncated data, or narrow the query to the specific events you need. The underlying trace data is never altered, only this response is bounded. Both detail modes enforce size limits; `detail: "full"` does not guarantee that every event or property fits.

# Reminders

- Always get the `traceId` from `query-llm-traces-list` results — do not guess or fabricate trace IDs.
- If no date range is provided, the default lookback window is used. For older traces, provide an explicit `dateRange`.
- The `events` array contains ALL events in the trace (including deeply nested ones), making this suitable for full tree reconstruction.
- Use `query-llm-traces-list` first to find traces, then this tool to inspect a specific one.
- Only ask for `detail: "full"` on a trace you have already narrowed down. A full-detail read of an unremarkable trace spends context you will need later.
