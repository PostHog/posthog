# Metrics: from internal on-call tool to customer-facing product

**Status:** proposal, 2026-07-08. Owners @daniel-v, #team-apm.
Companion to [`dashboard-mvp.md`](./dashboard-mvp.md) (the internal Grafana-replacement stack, largely shipped) and [`deployment-layout.md`](./deployment-layout.md) (what runs where).

## Goal

Two outcomes, in order:

1. **We stop needing Grafana for the logs/traces/metrics stack.** The on-call dashboard, its variables, its deploy annotations, and its alerts live in PostHog.
2. **Every PostHog customer can send metrics and build the dashboards they need for their services**, next to their product analytics, logs, traces, errors, and replays.

The differentiator is not chart parity with Grafana. It is that a metric spike in PostHog pivots to the raw emissions, the trace, the logs, the error, and the session in one product. Grafana structurally cannot do that.

## What the user experience should be

### Onboard (minutes, not hours)

Metrics appears in the product nav. The empty state (the existing `MetricsSetupPrompt`, which already polls `has_metrics` every 5s) becomes a real onboarding flow modeled on logs (`products/logs/frontend/onboarding/`), with two setup paths:

- **App metrics**: OTel SDK snippet per language. Point the OTLP exporter at `https://us.i.posthog.com/i/v1/metrics` (region-appropriate) with the project token. Any OTel-instrumented app works unmodified.
- **Infra / Prometheus metrics**: an OTel Collector recipe (`prometheus` receiver scraping their targets, `otlphttp` exporter to PostHog). Our internal `metrics-bridge` collector is the reference implementation; publish its shape as the customer recipe.

The prompt flips live when the first metric lands. No agent of ours to install, no datasource to configure.

### Explore

The `/metrics` Viewer, as shipped, plus the missing pieces: metric-name typeahead with an aggregation default inferred from `metric_type` (counter → `rate`, histogram → `histogram_quantile`), label filters, group-by, chart and stat modes, and a formula input (backend shipped in `formula.py`, no UI yet). HogQL SQL tab stays as the power-user escape hatch.

### Build dashboards

"Save as insight" from the Viewer. The insight lands on any dashboard as a normal tile next to product analytics, SQL, and error tracking tiles. Dashboard-level variables (the `$service` selector) fan into every metrics tile; project-wide deploy annotations overlay every chart. Dashboard templates built from OTel semantic-convention names ("Service health (RED)", "Kubernetes workload") light up automatically after onboarding.

### Alert

Alerts attach to insights, so metric insights inherit the alerts product (thresholds, anomaly detectors, on-chart threshold lines). Evaluation cadence needs an observability tier: insight alerts evaluate too slowly for paging, while logs alerting already runs fast ticks on a Temporal worker. Metric alerts should ride that pattern.

### Investigate

Click a spike, get the Samples panel (raw emissions with attributes; backend shipped as `metric_event_samples_query_runner`), click the `trace_id`, land in the trace, jump to correlated logs. None of this UI exists yet, and it is the reason to switch rather than merely tolerate.

## Decisions

| #   | Decision                | Recommendation                                                                                                                                                                                                                                                                               | Status                                                     |
| --- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| 1   | Dashboard query surface | A `MetricsQuery` node kind rendered as insight tiles. Widgets are barred for charts (`products/dashboards/CONTRIBUTING.md`), and insights give dashboards, alerts, subscriptions, sharing, and MCP for free. Precedent: `LogsQuery` registration in `posthog/hogql_queries/query_runner.py`. | Proposed; supersedes the widget plan in `dashboard-mvp.md` |
| 2   | Query UX                | Builder-first, not PromQL-first. The facade contract (metric + aggregation + filters + group-by + formula) already covers essentially every panel of the internal Grafana dashboard. HogQL is the escape hatch. PromQL compat (Track A) stays a separate migration-oriented read plane.      | Proposed                                                   |
| 3   | Ingest protocol         | OTLP only. The official Prometheus answer is "run a collector" (scrape → OTLP). We have empirical evidence the remote-write ecosystem is fragmented (RW 1.0 vs 2.0 broke our own bridge). No native remote-write endpoint for GA.                                                            | Proposed                                                   |
| 4   | Unit economics          | Keep byte-based quota/limits (consistent with logs, already implemented in the consumer) and add a per-team **active-series cap** as the cardinality guardrail. Ingest-assigned fingerprints + `metric_series` make active-series counting a cheap query. Label drop rules later.            | Open, gates opening ingest broadly                         |
| 5   | Retention               | Pick numbers before GA. `metrics1` and `metric_attributes` currently have **no TTL**; samples are 30d, series 90d. Proposal: 90d raw for alpha, revisit downsampled rollups for long ranges later.                                                                                           | Open; TTL migration is unwritten                           |
| 6   | Dashboard platform gaps | Fund the small deltas that make dashboards an on-call surface: variables binding into `MetricsQuery` tiles, annotations overlay on metric charts (today Trends-only), stat threshold coloring. Per-tile time override and alerts already exist.                                              | Proposed                                                   |
| 7   | Internal dogfood quota  | The internal-infra quota exemption (INFRA-B) was never implemented; scraped infra traffic rides normal team quota. Implement it or explicitly configure the internal project's limits.                                                                                                       | Open                                                       |
| 8   | Rollout mechanics       | Alpha flag → EA with onboarding + posthog.com docs → GA with pricing. Follow the logs sequence.                                                                                                                                                                                              | Proposed                                                   |

## Build map

| Journey stage | Exists                                                                                | Missing                                                                                      |
| ------------- | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Ingest        | OTLP endpoint, quota + rate limiting, prod both regions                               | remote-write story stays docs-only (collector recipe)                                        |
| Onboarding    | `has_metrics` polling empty state                                                     | wizard steps, SDK/collector snippets, posthog.com docs                                       |
| Explore       | Viewer (chart/stat, filters, group-by), SQL tab                                       | formula input                                                                                |
| Dashboards    | insight-tile platform (tile overrides, refresh, sharing)                              | `MetricsQuery` node kind, save-as-insight, variables binding, annotations overlay, templates |
| Alerts        | alerts product (thresholds + anomaly detectors), fast-tick precedent in logs alerting | metric alert wiring + observability-grade cadence                                            |
| Investigate   | samples + trace-pivot backend, anomaly characterization, `investigate` orchestrator   | Samples/trace-pivot UI, investigation surfacing                                              |
| Commercial    | byte quota, usage counters to app metrics                                             | active-series cap, retention TTLs, pricing                                                   |

## Sequencing

**Phase A: kill Grafana for ourselves.** `MetricsQuery` node kind + runner delegating to `run_metric_query` (no new facade methods) → `Query.tsx` rendering reusing the Viewer chart components → save-as-insight → dashboard variables binding → annotations overlay. Port the internal Grafana logs dashboard as the dogfood proof. The SQL-insight escape hatch works today for panels we want early.

**Phase B: open to customers.** Onboarding wizard + docs + collector recipe, dashboard templates, retention TTL migration, active-series cap, INFRA-B resolution, EA flag rollout.

**Phase C: the moat.** Samples/trace pivot UI, investigation and anomaly surfacing in the chart UX, faster alert cadence, label drop rules.

Each phase slices into stamp-track-sized PRs; Phase A is roughly five: schema node, runner registration, frontend rendering + save flow, variables, annotations.

## Non-goals

- PromQL as the in-product query language (Track A remains separate).
- A Prometheus remote-write ingest endpoint.
- The `metrics1` streams-table storage rewrite (unchanged from `dashboard-mvp.md`, seam is `attribute_field()`).
- Downsampling/rollups for GA (retention decision covers the interim).

## Open questions

1. Billing unit sign-off (decision 4): bytes with a series cap, or per-series pricing? Needs #team-billing-integrations input before EA.
2. Alert cadence: extend the alerts product with a faster interval tier, or run metric alerts on the logs-alerting Temporal pattern?
3. Where does the collector recipe live: posthog.com docs only, or a maintained Helm chart?
4. Do logs and traces also get first-class insight kinds on dashboards (mixed observability dashboards), and who owns that work?
