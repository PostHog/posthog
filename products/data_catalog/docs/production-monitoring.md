# Production monitoring of semantic-layer agent behavior

How we validate, on live hosted-MCP traffic, that agents honor the data catalog: checking `system.information_schema.metrics` before hand-writing SQL for a metric, running canonical metrics instead of re-deriving them, proposing metrics/certifications when appropriate, and preferring certified sources and accepted relationships.

All of this lives in PostHog's internal telemetry project (US project 2), where the hosted MCP server captures its analytics. The monitoring has three layers.

## 1. Dashboard tiles (HogQL over existing telemetry)

Tile group `7 · Agent behavior` on the "Data catalog usage" dashboard (project 2, dashboard 1902365):

- `7 · Catalog-first rate for KPI sessions`: share of KPI-intent SQL sessions whose metrics-catalog lookup preceded their first data-bearing query.
- `7 · KPI sessions that skip the catalog`: KPI-intent sessions with raw SQL and no catalog lookup or `data-catalog-metric-run` call.
- `7 · Semantic-layer lookups in SQL`: weekly lookups against `information_schema.metrics`, the `certification` column on `information_schema.tables`, and `information_schema.relationships`.
- `7 · KPI derivations vs agent proposals`: derivations without catalog engagement next to sessions where an agent called a catalog write tool.

Data sources: `$mcp_tool_call` events (tool names, ordering per `$session_id`) and the per-`execute-sql` `$ai_generation` events (`$ai_output_choices` carries the SQL text; `posthog.ai_events`, ~30 day retention). Session classification is regex-heuristic: SQL matching `information_schema.metrics` is a catalog lookup, other `information_schema`/`system.` references are schema discovery, everything else is data-bearing; KPI intent is a keyword match on the agent's stated intent.

## 2. Online evaluations (AI evals, `/ai-evals` in project 2)

**Live today:** `MCP: catalog checked before KPI derivation` (Hog, trace target, inactivity settle 5 min, 100% rollout, N/A allowed). Fails a session with KPI intent and data-bearing SQL but no prior successful catalog lookup and no `data-catalog-metric-run` span. Deterministic, no LLM cost. Its Hog source mirrors the tile classification above; results land as `$ai_evaluation` events.

### Writing Hog that survives real traces

A trace evaluation runs against traces of up to 500 events under a 10 second budget and a 64 MB VM, and **any** Hog failure disables the evaluation outright (`disables_evaluation=True` on `hog_error`), so a slow evaluation stops scoring until someone re-enables it. The first version of the evaluation above was disabled within minutes by `Execution timed out (10s limit exceeded)`. Three things caused it, all worth avoiding:

- **`and` does not short-circuit.** `Operation.AND` pops every operand, so `e.event == '$ai_span' and e.properties.$ai_span_name == '...'` does the property lookups on every event regardless of type. Nest `if` blocks instead of chaining conditions.
- **Regexes are compiled per call.** `=~*` with an alternation, evaluated once per event, dominated the budget. Use `lower()` once and then `like`.
- **Stop scanning once the verdict is latched.** Guard the expensive string work behind the state that makes it irrelevant, and `return` from inside the loop when no later event can change the answer.

Memory is a separate, rarer failure: reading a global does `deepcopy(...)` onto the 64 MB stack, so an oversized trace can exceed it before any of your code runs. Traces above 500 events are skipped upstream (`trace_too_large`), which catches the worst runaways, but a trace that passes that check with large payloads can still fail, and there is no Hog-side mitigation. Validate with `llma-evaluation-test-hog` against real traces before enabling, and check the evaluation's `status_reason_detail` if it goes quiet.

**Pending `trackToolSpan` deployment** (`services/mcp/src/hono/analytics.ts`): three LLM-judge trace evaluations, sampled low (5-10%) via `rollout_percentage`:

1. **Metric bypass**: the `$ai_span` for a catalog lookup carries the results (`$ai_output_state`), so the judge sees which metrics the lookup returned. Verdict: given an approved, non-drifted metric matching the session's intent, did the client run it via `data-catalog-metric-run`, or hand-write SQL for the same number?
2. **Proposal appropriateness**: given the session's intents, SQL, and tool spans, did the agent derive a reusable business metric with no canonical definition, and if so did it propose or offer to catalog it (landing `proposed`, disclosed as such)? One-off exploration must not trigger speculative proposals.
3. **Trust adherence**: given certification/relationship metadata the agent read, did the final SQL prefer `certified` over `deprecated` sources and use accepted join keys from `information_schema.relationships`?

Evaluation definitions are per-team database rows, not repo code; this document is their source of truth. When creating or editing them, validate Hog with the evaluation test endpoint (`llma-evaluation-test-hog`) against real traces first, and spot-check judge verdicts at a tiny rollout before trusting rates.

## 3. Instrumentation contract (`services/mcp`)

- Every MCP analytics event is stamped with `mcp_data_catalog_enabled` (the evaluated `product-data-catalog` flag) for cohort splits.
- `trackExecuteSqlGeneration` captures one `$ai_generation` per `execute-sql` call with the intent and SQL text; `$ai_trace_id` is the MCP session uuid, so a session is one trace.
- `trackToolSpan` captures an `$ai_span` (args + truncated results) for every tool by default, joining the same session trace, so a trace-target evaluation sees a call's args and result. Secret-bearing fields (passwords, `client_secret`, API keys, tokens) are redacted from both input and output before capture, so defaulting every tool on never lands a credential in telemetry.
- `execute-sql` is the one exception, because its payload is the query result and it serves all traffic. Spans are captured for its metadata queries only (SQL referencing `information_schema`, ~4.5% of calls): those results are small and describe what the agent knew about the workspace before writing its next query. That covers catalog lookups of `metrics`, `certifications`, and `relationships` without the telemetry layer naming them. The gate strips SQL comments and string literals before matching, so the marker inside a comment or literal on a data query does not pull the result into telemetry.

## Known limits

- The evaluation scheduler triggers only on `$ai_generation`, so sessions with no `execute-sql` call are never evaluated; they remain visible in the dashboard tiles via `$mcp_tool_call`.
- `posthog.ai_events` retention (~30 days) bounds every SQL-text-based measure.
- A single failing trace disables the whole evaluation rather than skipping that trace, so a rare oversized trace can silently stop scoring. Watch for the auto-disable email.
- The customer's catalog contents are not directly joinable from telemetry; "a matching metric existed" is judged from lookup results in spans, not from the source of truth.
