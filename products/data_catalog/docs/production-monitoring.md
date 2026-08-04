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

**Pending `trackToolSpan` deployment** (`services/mcp/src/hono/analytics.ts`): three LLM-judge trace evaluations, sampled low (5-10%) via `rollout_percentage`:

1. **Metric bypass**: the `$ai_span` for a catalog lookup carries the results (`$ai_output_state`), so the judge sees which metrics the lookup returned. Verdict: given an approved, non-drifted metric matching the session's intent, did the client run it via `data-catalog-metric-run`, or hand-write SQL for the same number?
2. **Proposal appropriateness**: given the session's intents, SQL, and tool spans, did the agent derive a reusable business metric with no canonical definition, and if so did it propose or offer to catalog it (landing `proposed`, disclosed as such)? One-off exploration must not trigger speculative proposals.
3. **Trust adherence**: given certification/relationship metadata the agent read, did the final SQL prefer `certified` over `deprecated` sources and use accepted join keys from `information_schema.relationships`?

Evaluation definitions are per-team database rows, not repo code; this document is their source of truth. When creating or editing them, validate Hog with the evaluation test endpoint (`llma-evaluation-test-hog`) against real traces first, and spot-check judge verdicts at a tiny rollout before trusting rates.

## 3. Instrumentation contract (`services/mcp`)

- Every MCP analytics event is stamped with `$mcp_data_catalog_enabled` (the evaluated `product-data-catalog` flag) for cohort splits.
- `trackExecuteSqlGeneration` captures one `$ai_generation` per `execute-sql` call with the intent and SQL text; `$ai_trace_id` is the MCP session uuid, so a session is one trace.
- `trackToolSpan` captures an `$ai_span` (args + truncated results) for tools that opt in. Opting in is declarative: this product sets `capture_trace_payload: true` at the category level in `products/data_catalog/mcp/tools.yaml`, which the generator folds into every catalog tool's definition. The shared analytics path reads that flag and knows nothing about the data catalog, so another product can enable payload capture for its own evaluations with one line of YAML.
- `execute-sql` is the exception the flag can't express, because its payload is the query result and it serves all traffic. Spans are captured for its metadata queries only (SQL referencing `information_schema`, ~4.5% of calls): those results are small and describe what the agent knew about the workspace before writing its next query. That covers catalog lookups of `metrics`, `certifications`, and `relationships` without the telemetry layer naming them.

## Known limits

- The evaluation scheduler triggers only on `$ai_generation`, so sessions with no `execute-sql` call are never evaluated; they remain visible in the dashboard tiles via `$mcp_tool_call`.
- `posthog.ai_events` retention (~30 days) bounds every SQL-text-based measure.
- Oversized traces can exceed the Hog memory limit and record an error instead of a verdict.
- The customer's catalog contents are not directly joinable from telemetry; "a matching metric existed" is judged from lookup results in spans, not from the source of truth.
