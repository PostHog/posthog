# Reading LLM traces over MCP

`query-llm-trace` and `query-llm-traces-list` accept an optional `detail` parameter:

| Value              | Content                                                                                               |
| ------------------ | ----------------------------------------------------------------------------------------------------- |
| `"full"` (default) | Full event properties, subject to response size limits.                                               |
| `"summary"`        | Trace and event metadata with short previews of prompts, outputs, span states, and custom properties. |

Omitting `detail` preserves the existing full-detail behavior. Summary mode is opt-in on both tools.
The MCP wrapper consumes this parameter; it is not part of the backend `TraceQuery` or `TracesQuery` schema.

## Investigation workflow

Use `detail: "summary"` to find candidate traces or survey a trace's events, costs, timing, and errors.
Summarized traces include `_detail: { "mode": "summary" }`.

Once a trace needs investigation, use `query-llm-trace` with `detail: "full"` and retain the relevant
date and property filters. Full detail is needed for exact tool arguments, conversation extraction,
and searches for content that a preview may omit. A known trace can be read in full directly.

The [exploring-llm-traces skill](../../products/ai_observability/skills/exploring-llm-traces/SKILL.md)
teaches this workflow and includes scripts for parsing saved full-detail responses.

## Response limits

Both modes compact large responses before returning them to the MCP client. The compactor accounts
for JSON escaping in values and keys, then checks the serialized result against its budget.
Summary mode has a smaller budget than full detail.

Long values, omitted array items or object keys, and dropped events or traces carry truncation markers.
`detail: "full"` does not disable these limits. Missing content in a truncated response does not prove
it was absent from the stored trace. Narrow the query or open the returned `_posthogUrl` for the complete data.
The stored trace is unchanged by response compaction.
