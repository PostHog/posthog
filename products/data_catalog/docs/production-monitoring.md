# Production monitoring of semantic-layer agent behavior

How we validate, on live hosted-MCP traffic, that agents honor the data catalog: checking `system.information_schema.metrics` before hand-writing SQL for a metric, running canonical metrics instead of re-deriving them, proposing metrics/certifications when appropriate, and preferring certified sources and accepted relationships.

All of this lives in PostHog's internal telemetry project (US project 2), where the hosted MCP server captures its analytics. The monitoring has three layers: keyword-gated dashboard tiles for free volume and trend, LLM-judge online evaluations for semantic verdicts, and the `services/mcp` instrumentation both depend on.

The division of labor follows one rule: **the judges decide what a session was trying to do; deterministic code only measures what mechanically happened.** A keyword list can never enumerate every way a person asks a metric question (measured coverage of the tile keywords: ~6.5% of SQL sessions), so any check that starts with "was this a metric question?" belongs to a judge. The tiles keep the keyword heuristic as a cheap trend signal, and the judges measure what it misses.

## 1. Dashboard tiles (HogQL over existing telemetry)

Tile group `7 · Agent behavior` on the "Data catalog usage" dashboard (project 2, dashboard 1902365):

- `7 · Catalog-first rate for KPI sessions`: share of KPI-intent SQL sessions whose metrics-catalog lookup preceded their first data-bearing query. Carries a fleet-wide series and a catalog-enabled series (`mcp_data_catalog_enabled = true`, property exists from Aug 5, 2026).
- `7 · KPI sessions that skip the catalog`: KPI-intent sessions with raw SQL and no catalog lookup or `data-catalog-metric-run` call, same two series.
- `7 · Semantic-layer lookups in SQL`: weekly lookups against `information_schema.metrics`, the `certification` column on `information_schema.tables`, and `information_schema.relationships`.
- `7 · KPI derivations vs agent proposals`: derivations without catalog engagement next to sessions where an agent called a catalog write tool.
- `7 · Semantic layer judge verdicts`: daily pass/fail/not-applicable counts from the three judge evaluations (matches both the current and pre-rename evaluation names).

Beyond group 7, the dashboard carries curation and quality tiles worth knowing: `2 · Catalog inventory (cumulative)` (running total of metrics, certification marks, accepted relationships), `3 · Review queue backlog (current)` (entities awaiting a human decision, from each entity's latest lifecycle event), and `5 · Canonical share of metric runs` (share of runs returning an approved, non-drifted result - the consumption quality signal).

Data sources: `$mcp_tool_call` events (tool names, ordering per `$session_id`) and the per-`execute-sql` `$ai_generation` events (`$ai_output_choices` carries the SQL text; `posthog.ai_events`, ~30 day retention). Session classification is regex-heuristic: SQL matching `information_schema.metrics` is a catalog lookup, other `information_schema`/`system.` references are schema discovery, everything else is data-bearing; KPI intent is a keyword match on the agent's stated intent. **The keyword match is a known undercount** - the judges below carry the semantic version of the same questions, and comparing the judges' applicability share against the tiles' keyword share over the same catalog-enabled population measures the keyword gate's miss rate.

## 2. Online evaluations (AI evals, `/ai-evals` in project 2)

Three LLM-judge trace evaluations, live since Aug 5, 2026. Common configuration: trace target, inactivity settle 300s, judge model `claude-haiku-4-5` on the "Team 2 evals" Anthropic provider key, boolean output with N/A allowed, **2% rollout**, conditions `$ai_product = mcp` AND `$ai_span_name = execute-sql` AND `mcp_data_catalog_enabled = true`. Results land as `$ai_evaluation` events. Cost at this configuration: roughly $70/month total.

| Evaluation                                                    | Premise | Verdict                                                                                                                                                                                                             |
| ------------------------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Semantic layer: canonical metric bypass (MCP judge)`         | 1       | Was the request a governed business measure, in any phrasing? If yes: catalog consulted before hand-written SQL, and an approved non-drifted match run via `data-catalog-metric-run` rather than re-derived?        |
| `Semantic layer: metric proposal appropriateness (MCP judge)` | 2       | Did the session derive a reusable business metric with no canonical definition? If yes: proposed or offered to catalog it, disclosed as landing `proposed`? Speculative proposals on one-off exploration also fail. |
| `Semantic layer: trust metadata adherence (MCP judge)`        | 3       | Did the agent read certification/relationship metadata? If yes: certified sources preferred over deprecated, accepted join keys used over guessed ones?                                                             |

Every rubric follows the same shape, and new judges should too: **classify applicability first, judge second, N/A on missing evidence.** The applicability step is where the judge replaces the keyword list - it decides semantically whether the premise applies to this session. The evidence rule matters because judge input is capped at 150k characters and long traces are uniformly sampled down (about a fifth of catalog-enabled traces exceed the cap): the rubric instructs the judge to answer N/A when it cannot see enough to decide, rather than guessing from a partial view.

### Reading the rates honestly

- **Compliance rates are conditional.** A judged trace only produces a pass/fail when the premise applied; the rest are N/A. At 2% rollout (~1,750 judged traces/month) with roughly a tenth of sessions being metric questions, expect on the order of 175 applicable verdicts/month, which puts about ±7 points on the monthly compliance rate. Report monthly, not weekly. Raising rollout to 5% (~$175/month) tightens this if needed.
- **The applicability share is itself a result.** It is the semantic answer to "what fraction of sessions are metric questions", and dividing the tile's keyword-matched share by it gives the keyword gate's measured miss rate.
- **Calibration gates publication.** Hand-read a few dozen verdicts per judge (verdict plus reasoning) before putting any pass-rate on the dashboard, and check specifically whether Haiku's reasoning is deep enough on proposal appropriateness - that judge has the subtlest call and is the candidate for moving to `claude-sonnet-4-6`.
- **There is no pre-enable test path for trace-target evaluations.** `evaluation_runs` rejects trace-target re-runs against a single generation, and the Hog test endpoint does not cover LLM judges, so validation happens by enabling at a small rollout and reading verdicts. Judge failures (parse errors, provider hiccups) do not auto-disable the evaluation the way Hog errors do.

Evaluation definitions are per-team database rows, not repo code; this document is their source of truth.

### Calibration log

- **Aug 2026, canonical metric bypass, first fail.** The first failing verdict was a scheduled Signals Scout run whose executed SQL was entirely schema and freshness validation (`information_schema` lookups, a max-date/row-count check), which is work the metric-discovery steering explicitly exempts as schema-first. The judge failed it on the run's surrounding context (a churn-scoring scout) rather than on the queries it executed. Two remediations: the scout harness prompt now carries a flag-gated catalog-first rule (`products/signals/backend/scout_harness/prompt.py`, the only repo surface reaching custom store-hosted scout skills, which steer with their own prescribed SQL), and the bypass rubric gained an applicability clause returning N/A when a trace computes no business measure. The offline suite (`products/data_catalog/evals/`) pins both sides: `scout_skill_prescribed_bypass` and `scout_schema_validation_control`.

### Retired: the deterministic Hog evaluation

`MCP: catalog checked before KPI derivation` (Hog) ran Aug 4-5, 2026 and is retired, disabled pending deletion. Two reasons. Its applicability gate was a keyword list, which required predicting every phrasing of a metric question and measurably covered ~6.5% of sessions - the judges classify semantically instead. And it duplicated the catalog-first tile's measurement with worse failure semantics: any single Hog failure disables the whole evaluation (`disables_evaluation=True` on `hog_error`), which took it offline twice in two days, once from a 10s timeout on a pathological trace and once when tool-span capture changed the traffic shape under it.

The Hog authoring constraints learned from those incidents still apply to any future Hog trace evaluation: `and` does not short-circuit (nest `if`s), regexes compile per call (use `lower()` + `like`), never iterate `evaluation_events` (index `evaluation_events[i]` with the bound from `trace.event_count`; Hog arrays are 1-indexed - iteration cost is proportional to total trace payload now that every tool call carries args and results), return early once the verdict is latched, scope conditions to the population you mean, and validate with `llma-evaluation-test-hog` against real traces before enabling. Memory is a separate hazard with no Hog-side mitigation: reading a global deepcopies it onto the 64 MB stack, so a large-payload trace under the 500-event cap can still fail.

## 3. Instrumentation contract (`services/mcp`)

- Every MCP analytics event is stamped with `mcp_data_catalog_enabled` (the evaluated `product-data-catalog` flag) for cohort splits.
- `trackExecuteSqlGeneration` captures one `$ai_generation` per `execute-sql` call with the intent and SQL text; `$ai_trace_id` is the MCP session uuid, so a session is one trace.
- `trackToolSpan` captures an `$ai_span` (args + truncated results) for every tool by default, joining the same session trace, so a trace-target evaluation sees a call's args and result. Secret-bearing fields (passwords, `client_secret`, API keys, tokens) are redacted from both input and output before capture, so defaulting every tool on never lands a credential in telemetry.
- `execute-sql` is the one exception, because its payload is the query result and it serves all traffic. Spans are captured for its metadata queries only (SQL referencing `information_schema`, ~4.5% of calls): those results are small and describe what the agent knew about the workspace before writing its next query. That covers catalog lookups of `metrics`, `certifications`, and `relationships` without the telemetry layer naming them. The gate strips SQL comments and string literals before matching, so the marker inside a comment or literal on a data query does not pull the result into telemetry.

## Known limits

- The evaluation scheduler triggers only on `$ai_generation`, so sessions with no `execute-sql` call are never evaluated; they remain visible in the dashboard tiles via `$mcp_tool_call`.
- `posthog.ai_events` retention (~30 days) bounds every SQL-text-based measure.
- Judge input is capped at 150k characters with uniform sampling beyond it, so verdicts on very long sessions lean on the N/A-on-missing-evidence rule; the compliance rate has a known blind spot on the fat tail.
- The customer's catalog contents are not directly joinable from telemetry; "a matching metric existed" is judged from lookup results visible in the trace, not from the source of truth.
