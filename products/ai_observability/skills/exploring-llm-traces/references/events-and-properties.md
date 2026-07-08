# AI observability event and property reference

## Event types

### `$ai_trace`

Top-level container for a trace. Emitted last, after all child events.

| Property           | Type   | Description                                                  |
| ------------------ | ------ | ------------------------------------------------------------ |
| `$ai_trace_id`     | string | Unique trace identifier — shared by all events in this trace |
| `$ai_trace_name`   | string | Name of the trace                                            |
| `$ai_session_id`   | string | Groups multiple traces into a session                        |
| `$ai_input_state`  | JSON   | Application state at trace start (can be very large)         |
| `$ai_output_state` | JSON   | Application state at trace end (can be very large)           |
| `$ai_latency`      | float  | Total trace duration in seconds                              |

### `$ai_span`

Logical grouping within a trace (e.g. "RAG retrieval", "tool execution", "routing").

| Property           | Type   | Description                |
| ------------------ | ------ | -------------------------- |
| `$ai_trace_id`     | string | Parent trace ID            |
| `$ai_span_id`      | string | Unique span identifier     |
| `$ai_span_name`    | string | Name of this span          |
| `$ai_parent_id`    | string | ID of parent span or trace |
| `$ai_latency`      | float  | Span duration in seconds   |
| `$ai_input_state`  | JSON   | State entering this span   |
| `$ai_output_state` | JSON   | State leaving this span    |

### `$ai_generation`

Individual LLM API call (e.g. a chat completion request).

| Property              | Type       | Description                                                          |
| --------------------- | ---------- | -------------------------------------------------------------------- |
| `$ai_trace_id`        | string     | Parent trace ID                                                      |
| `$ai_parent_id`       | string     | ID of parent span or trace                                           |
| `$ai_model`           | string     | Model identifier (e.g. "gpt-4o", "claude-sonnet-4-20250514")         |
| `$ai_provider`        | string     | Provider name (e.g. "openai", "anthropic")                           |
| `$ai_input`           | JSON array | Input messages — `{role, content}` objects. **Can be very large.**   |
| `$ai_output_choices`  | JSON array | LLM response — `{message: {role, content}}`. May include tool calls. |
| `$ai_input_tokens`    | int        | Tokens in the input                                                  |
| `$ai_output_tokens`   | int        | Tokens in the output                                                 |
| `$ai_input_cost_usd`  | float      | Cost of input tokens in USD                                          |
| `$ai_output_cost_usd` | float      | Cost of output tokens in USD                                         |
| `$ai_total_cost_usd`  | float      | Total cost in USD                                                    |
| `$ai_latency`         | float      | Generation duration in seconds                                       |
| `$ai_http_status`     | int        | HTTP status from the LLM API                                         |
| `$ai_is_error`        | boolean    | Whether the generation errored                                       |
| `$ai_error`           | string     | Error message if generation failed                                   |
| `$ai_base_url`        | string     | LLM API base URL                                                     |
| `$ai_tools_called`    | string     | Comma-separated tool names called by the LLM                         |

### `$ai_embedding`

Embedding creation event (text to vector).

| Property             | Type   | Description                |
| -------------------- | ------ | -------------------------- |
| `$ai_trace_id`       | string | Parent trace ID            |
| `$ai_parent_id`      | string | ID of parent span or trace |
| `$ai_model`          | string | Embedding model identifier |
| `$ai_provider`       | string | Provider name              |
| `$ai_input_tokens`   | int    | Tokens processed           |
| `$ai_total_cost_usd` | float  | Total cost in USD          |
| `$ai_latency`        | float  | Duration in seconds        |

## Where heavy content lives: `events` vs `ai_events`

The heavy LLM properties are **not stored on `events`** — they live as native columns on a dedicated
ClickHouse table, referenced in HogQL as **`posthog.ai_events`**. The `events` table keeps only the lightweight metadata (token counts, costs,
model, provider, `$ai_trace_id`, latency, error flags).

| Heavy content  | `events` property    | `ai_events` column |
| -------------- | -------------------- | ------------------ |
| Input messages | `$ai_input`          | `input`            |
| Output         | `$ai_output`         | `output`           |
| Output choices | `$ai_output_choices` | `output_choices`   |
| Input state    | `$ai_input_state`    | `input_state`      |
| Output state   | `$ai_output_state`   | `output_state`     |
| Tools          | `$ai_tools`          | `tools`            |

`posthog.ai_events` is `ORDER BY (team_id, trace_id, timestamp)`, so **`trace_id` is the access
path, not `timestamp`**. Rows are dropped after the retention period (30 days by default), so
traces older than that have no content. Nothing restricts which heavy columns an event can carry,
but the typical shape is: `$ai_generation` carries `input` / `output_choices` / `tools` (embeddings
carry `input`); `$ai_span` and `$ai_trace` carry `input_state` / `output_state`.

For trace inspection, prefer the `query-llm-trace` / `query-llm-traces-list` tools — they read
`posthog.ai_events` for you. Drop to the SQL below only for custom analysis (aggregations, joins,
batch extraction) or when you're already at the SQL layer.

**Single trace** — when you already have a `trace_id` (e.g. from a trace URL or `query-llm-traces-list`): read it directly.

```sql
SELECT timestamp, span_id, event, model, input, output_choices
FROM posthog.ai_events
WHERE trace_id = '<trace_id>'
ORDER BY timestamp
```

**Batch / analytics (a time window across many traces):** filter on the timestamp-indexed
`events` table first to get the trace IDs, then fetch the heavy content from `posthog.ai_events`
anchored on `trace_id`.

```sql
WITH matching_traces AS (
    SELECT DISTINCT properties.$ai_trace_id AS trace_id
    FROM events
    WHERE event = '$ai_generation'
        AND timestamp >= now() - INTERVAL 7 DAY
        AND properties.$ai_model = 'gpt-4o'  -- token/cost/model/ids stay on events
)
SELECT a.trace_id, a.span_id, a.model, a.input, a.output_choices
FROM posthog.ai_events AS a
WHERE a.trace_id IN (SELECT trace_id FROM matching_traces)
ORDER BY a.trace_id, a.timestamp
```

## Common patterns

### Linking events in a trace

All events share `$ai_trace_id`. The hierarchy is built via `$ai_parent_id`:

```text
$ai_trace (id: "trace-1", $ai_trace_id: "trace-1")
  └── $ai_span (id: "span-1", $ai_trace_id: "trace-1", $ai_parent_id: "trace-1")
        └── $ai_generation (id: "gen-1", $ai_trace_id: "trace-1", $ai_parent_id: "span-1")
```

### Cost aggregation

Costs are only on `$ai_generation` and `$ai_embedding` events.
Sum `$ai_total_cost_usd` across these for the same `$ai_trace_id` to get total trace cost.

### Large properties warning

These properties can contain megabytes of data:

- `$ai_input` — full conversation history, system prompts
- `$ai_input_state` / `$ai_output_state` — application state snapshots

Use `contentDetail: "preview"` or `"none"` when querying via MCP tools.
When using `contentDetail: "full"`, dump results to a file.

In raw SQL these live only on `posthog.ai_events`, not `events.properties` —
see [Where heavy content lives](#where-heavy-content-lives-events-vs-ai_events) for the column
mapping and query patterns.
