# Metrics: Investigate & Display UX

Design for the two jobs surfaced by the Logs-Capture latency incident
(2026-06-28): going from a fired alert to an evidenced root cause
(**investigate**), and turning that into a shareable artifact (**display**).
In that incident the investigation succeeded but with friction (capability
discovery, an off-by-a-day timestamp, corroboration via proxy metrics), and the
display was impossible — there is no OTel-metrics insight node, so the agent
baked static constants into HogQL line charts (accurate but dead).

## Decisions (2026-06-29, DRI: Daniel Visca)

1. **Investigate → shared primitives.** characterize / drill / pivot / correlate
   are one backend capability consumed by BOTH the conversational agent (MCP)
   and the in-app Metrics explorer. Not agent-only, not explorer-only.
2. **Display → incident-report artifact first.** A narrative + charts pinned to
   the incident window + cross-signal links, generated from an investigation.
   Live monitoring dashboard tiles come later — the report's chart generalizes
   into the dashboard insight node.

## The seam: `InvestigationResult`

The idea that makes both decisions cohere: **the shared primitive's output is
the report's input.** One structured DTO is produced once and consumed three
ways.

`InvestigationResult`:

- **symptom** — metric, magnitude, `onset_time`, `direction`, `change_ratio`
- **top_movers** — label values whose behaviour changed (localized vs shared cause)
- **verdicts** — normalized-vs-traffic, queue-wait-vs-slow-processing, etc.
- **evidence** — correlated log filters + exemplar `trace_id`/`span_id`
- **chart_specs** — the `query-metrics` clauses + pinned windows used
- **confidence** + **narrative**

- The **agent** renders it as narrative (Slack / Max).
- The **explorer** renders it as an interactive panel (anomaly highlight, mover
  chips, one-click pivot to logs/traces).
- The **report** serializes it into the shareable artifact.

One produce path, three consume paths. This is why "both surfaces" and "report
born from the investigation" are the same build, not three.

## Investigate — shared primitives

Facade-level capabilities (`products/metrics/backend/facade`), exposed to MCP
tools and the in-app API alike:

| primitive                                                                  | status                                                             |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `discover(symptom)` → metric names                                         | exists (`list_metric_names`)                                       |
| `characterize(metric, window, baseline?)` → anomaly summary                | exists (`characterize_metric_anomaly`)                             |
| `query(clauses, formula, filters, group_by, interval)` → series            | exists (`run_metric_query`)                                        |
| `pivot_to_traces(metric, filters, window)` → exemplar `trace_id`/`span_id` | **NEW** — from `metric_samples` trace columns (events-model stack) |
| `correlate(service, onset_window)` → log filters + APM spans               | compose `query-logs` + APM span tools                              |
| `investigate(alert_context \| metric+window)` → `InvestigationResult`      | **NEW** — the orchestrator that runs the loop                      |

The loop itself is already authored — the `investigating-metric-anomalies`
skill, whose worked example is literally this incident. "Shared primitives"
means making its steps callable capabilities that return **structured data**, so
the explorer can render exactly what the agent narrates.

**Differentiator:** the metric → trace pivot (`trace_id` on samples) answers
_why_, not just _what/when_. Grafana shows the chart; PostHog pivots to the slow
trace and the log line at onset. That is the reason to investigate here rather
than in Grafana, and it falls straight out of the events-model samples table.

## Display — incident-report artifact

Generated from an `InvestigationResult`:

- **narrative** — summary banner, root cause, blast radius, confidence
- **chart_specs** — query + pinned window, **re-runnable, not baked**: reopening
  the report re-runs the exact query over the exact window, so it shows the spike
  forever but is real data (the opposite of the transcript's baked HogQL constants)
- **cross-signal links** — exemplar `trace_id`s, the log filters used

**Host:** a dedicated artifact object, rendered with the explorer's existing
metrics chart component (reuse, don't rebuild). A Notebook is the obvious
narrative+embed host, but it's blocked by the same missing metrics-insight-node
gap and can't pin a window cleanly; a dedicated artifact lets us control
window-pinning and the structured links now, with notebook/dashboard embedding
as a later integration once the chart generalizes into a NodeKind.

## Build sequence (stacked PRs, on top of the events-model stack)

0. **[in progress]** events-model stack (#66163–#66196) — series/samples split;
   provides `trace_id`/`span_id` on samples (the pivot's data source).
1. **trace-pivot primitive** — read `metric_samples` for exemplar `trace_id`s in
   a window; facade + MCP. Builds on the PR4 samples endpoint.
2. **`InvestigationResult` DTO + `investigate()` orchestrator** — compose the
   loop into one structured result; MCP `investigate-metric`.
3. **incident-report artifact** — model + create-from-result; facade + API + MCP
   `incident-report-create`.
4. **report rendering (frontend)** — reuse the metrics chart component for
   pinned-window charts + narrative + cross-signal links; shareable link.
5. **[later]** generalize the report chart into a dashboard metrics insight
   NodeKind — the live-monitoring tiles.

## Parallel keystone (does not block the artifact)

**Prometheus remote-write ingest** — so investigations run on the alert's _own_
series (e.g. Envoy `rq_time`), not proxies. Until this lands, every infra
investigation is corroboration-by-proxy, exactly like the transcript.

## Cheap early win

Alerts carry **structured context** (metric, fire-time UTC, threshold, service)
plus an "Investigate" action that calls `investigate()` with that context.
Deletes the off-by-a-day timestamp math and the "do you even have access?"
opening in one move.
