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

Three LLM-judge trace evaluations, live since Aug 5, 2026. Common configuration: trace target, inactivity settle 300s, boolean output with N/A allowed, conditions `$ai_product = mcp` AND `$ai_span_name = execute-sql` AND `mcp_data_catalog_enabled = true` AND `$session_id` is set (the last condition excludes the stateless-dialect orphan traces that mint a fresh trace id per event; added Aug 14, 2026). The bypass judge runs at **25% rollout** on `gpt-5.6-luna` (a pinned team provider key) for the release-gate window; the other two stay at 10% on `claude-haiku-4-5`. Results land as `$ai_evaluation` events.

| Evaluation                                                    | Premise | Verdict                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Semantic layer: canonical metric bypass (MCP judge)`         | 1       | Did the session compute a named, reusable measure - business or operational telemetry computed for monitoring or reporting - in any phrasing? If yes: catalog consulted before hand-written SQL, and an approved non-drifted match run via `data-catalog-metric-run` rather than re-derived? |
| `Semantic layer: metric proposal appropriateness (MCP judge)` | 2       | Did the session derive a reusable metric - business or operational - with no canonical definition? If yes: proposed or offered to catalog it, disclosed as landing `proposed`? Speculative proposals on one-off exploration also fail.                                                       |
| `Semantic layer: trust metadata adherence (MCP judge)`        | 3       | Did the agent read certification/relationship metadata? If yes: certified sources preferred over deprecated, accepted join keys used over guessed ones?                                                                                                                                      |

Every rubric follows the same shape, and new judges should too: **classify applicability first, judge second, N/A on missing evidence.** The applicability step is where the judge replaces the keyword list - it decides semantically whether the premise applies to this session. The evidence rule matters because judge input is capped at 150k characters and long traces are uniformly sampled down (about a fifth of catalog-enabled traces exceed the cap): the rubric instructs the judge to answer N/A when it cannot see enough to decide, rather than guessing from a partial view.

### Reading the rates honestly

- **Compliance rates are conditional.** A judged trace only produces a pass/fail when the premise applied; the rest are N/A. Sizing scales off the observed ~1,750 judged traces/month per 2% of traffic: the bypass judge at 25% sees on the order of 22,000 judged traces/month, the other two about 8,700 each. With roughly a tenth of sessions being metric questions, that is ~2,200 applicable verdicts/month on the bypass judge and ~870 on the others, putting about ±2 and ±3 points on the monthly compliance rate. Read the 10% judges monthly, not weekly; the bypass judge holds up weekly (~±4 points) while the gate rollout lasts. Raising rollout tightens this at proportional cost.
- **Attribute a failure by MCP consumer and client, not by distinct id.** One distinct id covers several internal agent workloads at once (Signals scout sandboxes, Desktop, tasks), so a prefix match reads as one cohort when it is many. `$mcp_consumer` plus `$mcp_client_name` on the trace's generations separates them. Dashboard tile: "7 · Bypass fails by cohort (internal fleet vs rest)".
- **The applicability share is itself a result.** It is the semantic answer to "what fraction of sessions are metric questions", and dividing the tile's keyword-matched share by it gives the keyword gate's measured miss rate.
- **Calibration gates publication.** Hand-read a few dozen verdicts per judge (verdict plus reasoning) before putting any pass-rate on the dashboard, and check specifically whether Haiku's reasoning is deep enough on proposal appropriateness - that judge has the subtlest call and is the candidate for moving to `claude-sonnet-4-6`.
- **There is no pre-enable test path for trace-target evaluations.** `evaluation_runs` rejects trace-target re-runs against a single generation, and the Hog test endpoint does not cover LLM judges, so validation happens by enabling at a small rollout and reading verdicts. Judge failures (parse errors, provider hiccups) do not auto-disable the evaluation the way Hog errors do.

Evaluation definitions are per-team database rows, not repo code; this document is their source of truth.

### Calibration log

- **Aug 2026, canonical metric bypass, first fail.** The first failing verdict was a scheduled Signals Scout run whose executed SQL was entirely schema and freshness validation (`information_schema` lookups, a max-date/row-count check), which is work the metric-discovery steering explicitly exempts as schema-first. The judge failed it on the run's surrounding context (a churn-scoring scout) rather than on the queries it executed. Two remediations: the scout harness prompt now carries a flag-gated catalog-first rule (`products/signals/backend/scout_harness/prompt.py`, the only repo surface reaching custom store-hosted scout skills, which steer with their own prescribed SQL), and the bypass rubric gained an applicability clause returning N/A when a trace computes no business measure. The offline suite (`products/data_catalog/evals/`) pins both sides: `scout_skill_prescribed_bypass` and `scout_schema_validation_control`.
- **Aug 2026, canonical metric bypass, second fail: the KPI-only scope split the surfaces.** The next failing verdict was a scheduled Signals Scout run that computed fleet operational telemetry (cost per run, terminal-failure rate) verbatim from its skill's prescribed sweeps, with the catalog-first harness rule live in its prompt. Every steering surface scoped catalog-first to business KPIs, so the scout was right to skip the catalog by its own rules, while the bypass judge counted operational rates as "KPI-shaped" and failed the run; the proposal judge classified the same trace as operational observation (N/A), so the two judges disagreed on applicability. Resolution: the definition broadened rather than the judge narrowing. "Metric" now means any named, reusable measure - business or operational telemetry computed for monitoring or reporting - across the harness rule, the MCP metric-discovery templates, and both judge rubrics; the scout fleet's own measures were seeded as governed metrics (`scout_cost_per_run`, `scout_run_fail_pct`) and the scouts-dashboard skill now runs them through `data-catalog-metric-run` with its raw sweeps demoted to labeled-noncanonical fallbacks. The offline suite pins the new boundary from both sides: `scout_operational_telemetry_bypass` and `scout_operational_no_match`.
- **Aug 2026, full-window audit: prose steering alone produced probabilistic compliance, so the catalog lookup became structural.** A 30-day read of every verdict found the judges healthy (fail reasonings accurate, N/A correctly excluding ad-hoc debugging and support work) and the behavior real: the bypass judge logged 54 fails against 1 pass among applicable sessions, roughly two thirds of them scheduled Signals Scout runs following their skills' prescribed sweeps, the rest one-shot and interactive agent sessions. The single pass and several same-shaped fails landed in the same post-broadening window, which is the signature of a one-line rule losing to a skill cookbook most of the time. Resolution: the scout harness now pre-fetches the team's approved, non-drifted metric names itself (`approved_metric_names_for_team` on the data-catalog facade) and injects them into the run prompt - names only, to keep the injection to a handful of tokens - so every catalog-enabled scout run is catalog-aware by construction; a scout reads a listed name's definition only when it matches the measure at hand, and the probe-and-cache prose rule survives only as the fallback for a failed lookup. Companions in the same pass: two more governed scout measures (`mcp_tool_call_fail_pct`, `slo_explicit_burn_by_operation`) with their skills updated to run them canonically (inbox-report-rubrics deliberately skipped - its checks are versioned and still moving, and freezing a definition mid-churn is worse than none); the trust judge's one fail traced to the `answer-billing-questions` skill, whose data-sources reference now names the certified invoice source and requires a stated reason when dropping to the raw mirror; and an offline regression experiment over an AI-evals dataset of the observed failure shapes: `products/data_catalog/scripts/offline_governance_experiment.py` replays each dataset item as a fresh hosted-MCP session, scores the trace with the live judge rubrics, and reports into the offline experiments view (`/ai-evals/evaluations/offline/experiments`); the dataset itself is curated at `/ai-evals/datasets`.

- **Aug 2026, post-injection audit: compliance moved out of the judged trace, so the statement became the contract.** With the injected listing live and the orphan filter applied, the bypass judge's failing population split three ways. Most fails computed measures with no governed metric and showed no trace-visible catalog consultation at all: the injection had removed the in-session lookup, and the "say no catalog metric matched" clause was a buried trailer that runs dropped while keeping the cheap `noncanonical` label (which the rubric deliberately does not credit). Nearly every pass ran one of the seeded scout-ops metrics canonically, confirming that a governed metric for the exact measure is the one robustly passing shape. The fragmentation hypothesis was confirmed but bounded: about a third of failing traces held a single generation, and about a quarter of non-scout fails had a same-user catalog lookup in a different trace the same day, invisible to the judged trace; there is no server-side conversation id to join on, so the fix is per-turn self-documentation, not plumbing. Remediations: the harness injection variants and the MCP metric-discovery steering now require opening the derivation query's stated context with `governed catalog consulted: no listed metric matched <measure> (noncanonical)` (the empty-catalog variant gained the statement too, having previously offered no pass path at all); the rubric enumerates the accepted statement forms and clarifies that supplemental drill-down SQL after running the matching canonical metric passes, since near-identical drill-down sessions had drawn opposite verdicts; and the recurring ungoverned scout measures got a seeding batch of proposed metrics. The offline suite pins the new boundaries from both sides: `scout_injected_listing_no_match` and `governed_metric_canonical_then_drilldown`.

### Retired: the deterministic Hog evaluation

`MCP: catalog checked before KPI derivation` (Hog) ran Aug 4-5, 2026 and is retired, disabled pending deletion. Two reasons. Its applicability gate was a keyword list, which required predicting every phrasing of a metric question and measurably covered ~6.5% of sessions - the judges classify semantically instead. And it duplicated the catalog-first tile's measurement with worse failure semantics: any single Hog failure disables the whole evaluation (`disables_evaluation=True` on `hog_error`), which took it offline twice in two days, once from a 10s timeout on a pathological trace and once when tool-span capture changed the traffic shape under it.

The Hog authoring constraints learned from those incidents still apply to any future Hog trace evaluation: `and` does not short-circuit (nest `if`s), regexes compile per call (use `lower()` + `like`), never iterate `evaluation_events` (index `evaluation_events[i]` with the bound from `trace.event_count`; Hog arrays are 1-indexed - iteration cost is proportional to total trace payload now that every tool call carries args and results), return early once the verdict is latched, scope conditions to the population you mean, and validate with `llma-evaluation-test-hog` against real traces before enabling. Memory is a separate hazard with no Hog-side mitigation: reading a global deepcopies it onto the 64 MB stack, so a large-payload trace under the 500-event cap can still fail.

## 3. Instrumentation contract (`services/mcp`)

- Every MCP analytics event is stamped with `mcp_data_catalog_enabled` (the evaluated `product-data-catalog` flag) for cohort splits.
- `trackExecuteSqlGeneration` captures one `$ai_generation` per `execute-sql` call with the intent and SQL text; `$ai_trace_id` is the MCP session uuid, so a session is one trace.
- `trackToolSpan` captures an `$ai_span` (args + truncated results) for every tool by default, joining the same session trace, so a trace-target evaluation sees a call's args and result. Secret-bearing fields (passwords, `client_secret`, API keys, tokens) are redacted from both input and output before capture, so defaulting every tool on never lands a credential in telemetry.
- `execute-sql` is the one exception, because its payload is the query result and it serves all traffic. Spans are captured for its metadata queries only (SQL referencing `information_schema`, ~4.5% of calls): those results are small and describe what the agent knew about the workspace before writing its next query. That covers catalog lookups of `metrics`, `certifications`, and `relationships` without the telemetry layer naming them. The gate strips SQL comments and string literals before matching, so the marker inside a comment or literal on a data query does not pull the result into telemetry.

## 4. Prometheus metrics and alerts

Everything above measures agent behavior. This section measures the product itself: whether catalog reads, metric runs, and join probes are working. Everything in the data catalog runs synchronously inside web requests, so these are plain `prometheus_client` instruments scraped from the web pods.

The instruments ship in this repo: the run and probe counters in `products/data_catalog/backend/metrics.py`, the read counters in `posthog/hogql/database/data_catalog_metrics.py` (core cannot import product internals, and the loaders that set them live in core). The alert rules do not ship here: vmalert rules live in the private PostHog/charts repo, and Grafana dashboards are UI-managed. The expressions below are the proposed starting points to land there. Every label combination is pre-created at import, so an expression can be validated against live series before any incident.

### Metrics

| Metric                                             | Labels                       | What it measures                                                  |
| -------------------------------------------------- | ---------------------------- | ----------------------------------------------------------------- |
| `posthog_data_catalog_reads_total`                 | `surface`                    | Catalog reads attempted. The denominator for the failure counter. |
| `posthog_data_catalog_read_failures_total`         | `surface`                    | Catalog reads that failed and returned an empty result.           |
| `posthog_data_catalog_metric_runs_total`           | `definition_kind`, `outcome` | Canonical metric runs, exactly one per invocation.                |
| `posthog_data_catalog_metric_run_duration_seconds` | `kind`                       | Blocking metric runs that returned results.                       |
| `posthog_data_catalog_relationship_probe_total`    | `outcome`                    | Live join probes run while accepting a relationship proposal.     |

`surface` names the read that broke, not the model it reads:

| `surface`                | Loader                            | What disappears when it fails                                                                 |
| ------------------------ | --------------------------------- | --------------------------------------------------------------------------------------------- |
| `metrics`                | `_catalog_metrics`                | `information_schema.metrics` returns no rows.                                                 |
| `tables`                 | `_catalog_certifications`         | The `certification` column on `information_schema.tables` reads as null.                      |
| `certifications`         | `_catalog_certification_rows`     | `information_schema.certifications` returns no rows.                                          |
| `relationships`          | `_catalog_accepted_relationships` | Accepted joins lose their confidence and reasoning.                                           |
| `relationship_proposals` | `_catalog_relationship_proposals` | The review queue reads as empty.                                                              |
| `table_visibility`       | `_catalog_table_visible`          | Individual relationship and certification rows vanish while their own loader reports success. |
| `schema_serialization`   | `_settled_catalog_certifications` | Trust marks vanish from the serialized database schema.                                       |

No counter carries `team_id`. Each increment sits next to a `logger.exception` that does, so the counter says something is broken and the structured log says for whom.

### How a failed query picks its outcome

Both the run counter and the probe counter classify a failed query with `classify_query_error`, the same function the query SLO path uses. That keeps three classes of failure out of the buckets people alert on:

| `classify_query_error` category | Metric run outcome  | Probe outcome       |
| ------------------------------- | ------------------- | ------------------- |
| `USER_ERROR`                    | `definition_error`  | `join_invalid`      |
| `QUERY_PERFORMANCE_ERROR`       | `query_performance` | `query_performance` |
| `RATE_LIMITED`                  | `capacity`          | `capacity`          |
| `CANCELLED`                     | `cancelled`         | `cancelled`         |
| `ERROR`                         | `internal_error`    | `error`             |

The distinction is not cosmetic. A metric that times out is the query's cost, not a rotten definition, so it must not raise the rot ratio. A ClickHouse error that the classifier calls `ERROR` (an unreadable Parquet file, an S3 object that changed under a warehouse table) is ours to fix, so it must not read as a user's broken definition. A timeout on a join probe does not mean the probe is broken, so it must not page.

`concurrency_limited` stays separate from `capacity`: it is the API concurrency limiter rejecting the run with a 429, not the shared ClickHouse pool saturating.

### Proposed alerts

**Catalog reads are failing** (warning, not a page). Every read path is fail-soft, so a broken catalog looks to an agent exactly like an empty one. This is the only signal that the difference exists.

```promql
sum by (surface) (increase(posthog_data_catalog_read_failures_total[15m])) > 5
```

A rate threshold rather than `> 0`: one team with a poisoned metric definition increments on every read until someone fixes it, and a `> 0` page could never resolve. During triage, divide by `posthog_data_catalog_reads_total` for blast radius and read the `team_id` from the logs.

**Metric runs are hitting system faults** (page). `internal_error` is the only outcome that means PostHog broke rather than a definition, a cost guardrail, or a user.

```promql
sum(increase(posthog_data_catalog_metric_runs_total{outcome="internal_error"}[15m])) > 0
```

**Governed metrics are rotting** (warning). Definitions that no longer run against the current schema.

```promql
(
  sum(increase(posthog_data_catalog_metric_runs_total{outcome=~"definition_error|invalid_query|internal_error"}[30m]))
  /
  sum(increase(posthog_data_catalog_metric_runs_total{outcome!="async_enqueued"}[30m]))
) > 0.2
and
sum(increase(posthog_data_catalog_metric_runs_total{outcome!="async_enqueued"}[30m])) > 20
```

The threshold and the minimum-volume guard are starting numbers and want tuning against real traffic. `async_enqueued` leaves the denominator because an enqueue has no outcome yet. `query_performance`, `capacity`, and `cancelled` stay in the denominator and out of the numerator: those runs happened, and none of them says the definition is stale.

**The join probe is broken** (page). No relationship can be accepted while it is.

```promql
sum(increase(posthog_data_catalog_relationship_probe_total{outcome="error"}[15m])) > 0
```

There is deliberately no alert on `concurrency_limited`. That condition already has one on `posthog_clickhouse_query_concurrency_limit_exceeded{product="data_catalog"}`, and a second series measuring the same thing would page twice for one incident.

### What these metrics do not cover

- **Async metric runs end at the enqueue.** `outcome="async_enqueued"` records that a query status was handed back to poll. Whether that run later succeeded lands in the generic worker-side query series, not here.
- **Governance actions** (create, approve, certify, accept, reject) are covered by the capture events in `backend/logic/analytics.py`. Their failures are user-caused 4xx, and django_prometheus middleware already covers 5xx.
- **Backlog size** (pending proposals, drifted approved metrics) needs a periodic sweep, and the product has no background job. Adding it means a `PushGatewayTask` Celery beat entry.

### Follow-ups

- A p95 duration alert on `posthog_data_catalog_metric_run_duration_seconds`. Deferred because the product is flag-gated and low-volume, so the alert would flap. The expression is `histogram_quantile(0.95, sum by (le, kind) (rate(posthog_data_catalog_metric_run_duration_seconds_bucket[30m])))`, validatable today against the pre-created series.
- OTLP twins through `OtelInstrumentFactory`, so the same series also land in the PostHog Metrics product.
- A counter on the scout harness's fail-silent catalog context injection (`products/signals/backend/scout_harness/runner.py`), exported through the data catalog facade.
- The backlog gauges described above.

## Known limits

- The evaluation scheduler triggers only on `$ai_generation`, so sessions with no `execute-sql` call are never evaluated; they remain visible in the dashboard tiles via `$mcp_tool_call`. A session that answers its question through a `query-*` tool instead of writing SQL is the common shape here, so the judged population is narrower than "catalog-enabled sessions".
- A judged trace is one MCP transport session, which is a complete run for scheduled scouts but can be a single turn for interactive clients that open a session per request. `$ai_session_id` is never stamped on MCP events and no conversation id exists server-side, so a catalog check on an earlier turn is invisible to the judged trace; the stated-context line on each data-bearing query is the mitigation, and the residual undercount concentrates in interactive traffic.
- `posthog.ai_events` retention (~30 days) bounds every SQL-text-based measure.
- Judge input is capped at 150k characters with uniform sampling beyond it, so verdicts on very long sessions lean on the N/A-on-missing-evidence rule; the compliance rate has a known blind spot on the fat tail.
- The customer's catalog contents are not directly joinable from telemetry; "a matching metric existed" is judged from lookup results visible in the trace, not from the source of truth.
