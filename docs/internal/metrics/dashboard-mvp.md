# Metrics Dashboard MVP — Replacing the Grafana logs.json inside PostHog

**Status:** designed 2026-06-11; synced with shipped state 2026-07-08. Owners @daniel-v, #team-apm (@jonmcwest, @frankh).
Phases 0-2 and the viewer (P8) have shipped. The infra bridge shipped in a different shape than planned (see Phase 1 outcome below).
The dashboard-integration phase (P10+) is superseded: the dashboards platform now disallows chart-primary widget types, so metrics tiles will ship as insight tiles instead (see Phase 3).
**Sibling docs:** the Prometheus-ecosystem read plane (Track A) is a separate stack outside this repo, out of scope here.

## Why

The cluster's `logs.json` Grafana dashboard (≈60 panels, source: `PostHog/grafana-dashboards/logs.json`) is the on-call surface for the logs / traces / metrics ingestion stack.
We already store metrics natively in `metrics1` on the logs ClickHouse cluster.
This doc scopes the work to render that exact dashboard inside PostHog (`/dashboard/...`) against `posthog.metrics`, so on-call can leave Grafana behind.

Native PostHog Metrics stays the user-facing product. The Prometheus-ecosystem read plane (prom-compat, Track A) is a separate stack outside this repo, reading the same storage.

## Non-goals (deliberately deferred)

1. Schema rewrite to the streams-table pattern (Snuffle benchmarks: ~10× disk on metrics, ~5× on logs).
   The seam for that rewrite is the `attribute_field()` helper introduced in P0.
2. PromQL / `prom-compat` service — separate stack, already designed.
3. SDK swap (replacing `prom-client` in `nodejs/src/...` with OTel SDK).
4. Deploy-annotation automation from Helm release events.

## What's already in place (do not re-build)

**Ingest data plane** — shipped or in-flight:

- `rust/capture-logs/`: OTLP/HTTP receiver at `/v1/metrics` (and `/i/v1/metrics`), JSON or protobuf, writes to Kafka. `rust/capture-logs/src/main.rs:154-160`, `src/service.rs:703-820`.
- `nodejs/src/ingestion/pipelines/metrics/metrics-ingestion-consumer.ts`: drains Kafka into ClickHouse with quota + ratelimit (`MetricsRateLimiterService`).
- ClickHouse `metrics1` table (OTel-shaped, gauge / sum / histogram / exp-histogram / summary), MVs into `metric_attributes`. `posthog/clickhouse/metrics/metrics1.py`. Registered in `posthog/clickhouse/schema.py:332-333`.
- `charts`: WarpStream metrics cluster + `kafka.metricsBrokers` on capture-logs + `/i/v1/metrics` Contour ingress + `metrics-ingestion`, live in prod-us + prod-eu (charts#11702, merged 2026-06-03).
- `posthog-cloud-infra`#8321/8322/8415/8434/8489 (merged): Kafka topics + S3 bucket + IRSA + CH named collection + Postgres app user.
- `argocd/otel-collector/` (daemonset, already deployed): an existing OTel Collector with `prometheus` + `otlp` receivers and a `metrics` pipeline whose exporter today is `debug`.

**Product surface — alpha (gated by `FEATURE_FLAGS.METRICS`), as shipped:**

- `products/metrics/backend/facade/api.py`: `team_has_metrics`, `run_metric_query` (multi-clause + server-side formula), `list_metric_names`, `list_metric_event_samples`, `characterize_metric_anomaly`, `investigate`. Contracts in `facade/contracts.py`, wire shape `[{labels, points}]`.
- `products/metrics/backend/metric_query_runner.py`: label filters with `resource | attribute | auto` scope, group-by on a shared interval grid, aggregations `sum | avg | count | p95 | rate | increase | histogram_quantile` (temporality-aware, counter-reset clamped), auto-bucketed to ~60 points.
- `products/metrics/frontend/MetricsScene.tsx`: multi-series Viewer (chart + stat modes, filters, group-by) + HogQL SQL editor over `posthog.metrics`. No formula input in the Viewer yet (backend `formula.py` shipped, UI did not).
- MCP tools in `products/metrics/mcp/tools.yaml`: `query-metrics`, `metric-names-list`, `characterize-metric-anomaly` (the original "MCP is a follow-on" note below is obsolete).
- Events model for drill-down: `metric_samples` / `metric_series` split with ingest-assigned series fingerprints, live in prod both regions since 2026-07-02.

## Gap to close (status as of 2026-07-08)

|                       | Status | Notes                                                                                      |
| --------------------- | ------ | ------------------------------------------------------------------------------------------ |
| Filters               | ✅     | label / attribute predicates with explicit scope (`resource` / `attribute` / `auto`)       |
| Group-by              | ✅     | shared interval grid, multi-series response                                                |
| Aggregations          | ✅     | `rate`, `increase`, `histogram_quantile` shipped alongside sum / avg / count / p95         |
| Multi-metric          | ✅     | N clauses + server-side formula (`backend/formula.py`); no formula input in the Viewer yet |
| Storage seam          | ✅     | `attribute_field(name)` helper used everywhere                                             |
| Wire shape            | ✅     | `[{labels, points}]`                                                                       |
| Dashboard tiles       | ❌     | superseded plan: insight tiles via a `MetricsQuery` node kind, not a widget (see Phase 3)  |
| Dashboard variables   | ❌     | dashboard filters propagate into metric insight tiles                                      |
| Annotations           | ❌     | PostHog Annotations render as vertical lines on metric charts                              |
| Scraped infra metrics | ✅     | via the dedicated `metrics-bridge` scrape collector, dev + prod (see Phase 1 outcome)      |
| MCP                   | ✅     | `query-metrics`, `metric-names-list`, `characterize-metric-anomaly`                        |

## Architecture (target)

```text
[ envoy /stats/prometheus       ]                  [ posthog services /metrics ]
[ kminion /metrics              ]   ──scrape──>    [ metrics-bridge collector  ]   ──OTLP/HTTP──>   capture-logs /i/v1/metrics
[ kube-state-metrics, cadvisor  ]                  [ prometheus receiver       ]                            │
[ node-exporter                 ]                  [ otlphttp/posthog exporter ]                            │
                                                                                                            ▼
                                                                                                          Kafka
                                                                                                            │
                                                                                                            ▼
                                                                                               metrics-ingestion-consumer
                                                                                                            │
                                                                                                            ▼
                                                                                            ClickHouse metrics1 (logs cluster)
                                                                                                            │
                                                ┌───────────────────────────────────────────────────────────┴────────────────────────────────────┐
                                                ▼                                                                                                ▼
                                  products/metrics facade                                                                          services/prom-compat (Track A, separate)
                                  (HogQL on metrics1 — this stack)                                                                 (PromQL on metrics1)
                                                │                                                                                                ▲
                                                ▼                                                                                                │
                              MetricsScene + metric_timeseries widget                                                            Grafana / alertmanager / promtool
```

## The stack

Twenty-three PRs, each <400 LOC including tests. Each is a separate `gt create` on top of the previous.

### Phase 0 — Foundations (no user-visible change, lock the seams)

| #      | Repo    | PR                                                                                                                                                                                                                           | Notes                                                                        |
| ------ | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| **P0** | posthog | `attribute_field(name) -> ast.Expr` helper + `seed_metric(team, name, points, labels)` pytest fixture                                                                                                                        | Schema-rewrite seam (see Non-goal 1) + deterministic test data.              |
| **P1** | posthog | `MetricQueryClause`, `MetricQueryRequest`, `MetricSeries`, `Point` frozen dataclasses in `products/metrics/backend/facade/contracts.py`. Facade stub raises NotImplementedError for unimplemented fields.                    | Locks the target wire shape from PR1 onward — no schema churn through P3-P7. |
| **P2** | posthog | DRF serializer + viewset accepts new request shape, returns `[MetricSeries]` (length-1 today). Regenerate TS types via `hogli build:openapi`. Old single-metric viewer kept on the legacy code path with a deprecation TODO. | After this PR every later backend PR regenerates TS types.                   |

### Phase 1 — Charts infra: turn on the existing collector's metrics pipeline

| #           | Repo    | PR                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Notes                                                                                  |
| ----------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **INFRA-A** | charts  | Add `otlphttp/posthog-metrics` exporter and a scoped `scrape_configs` block to the existing `argocd/otel-collector/` daemonset. **Dev cluster only**, scrape only the dashboard's targets (envoy capture-logs cluster, kminion ingestion-(logs\|traces) group, kube-state for capture-logs + logs-ingestion + metrics-ingestion + ingestion-(logs\|traces) deployments). Dual-write with `debug` exporter so the data flow can be inspected on day one. | Per-target list is the cardinality guardrail — no namespace wildcard.                  |
| **INFRA-B** | posthog | Add an `internal-infra` exemption (or a generous fixed quota) for the project token used by the otel-collector to `posthog/nodejs/src/metrics-ingestion/services/metrics-rate-limiter.service.ts`.                                                                                                                                                                                                                                                      | Without this the cluster's own metric traffic counts toward customer quota.            |
| **INFRA-C** | charts  | Cut `otlphttp/posthog-metrics` over from dual-write to single-write (drop `debug`). Dev only.                                                                                                                                                                                                                                                                                                                                                           | Validation gate before prod.                                                           |
| **INFRA-D** | charts  | Replicate INFRA-A + INFRA-C to `values.prod-us.yaml` and `values.prod-eu.yaml`.                                                                                                                                                                                                                                                                                                                                                                         | Lands after `daniel/metrics-prod-rollout` merges and CH `metrics1` is applied in prod. |
| **INFRA-E** | charts  | Broaden scrape config to the remaining targets the full dashboard needs (`capture-logs`, `logs-ingestion`, `metrics-ingestion` `/metrics` endpoints once SDK side is verified).                                                                                                                                                                                                                                                                         | Gates on P9 (UI can render) so we can sanity-check live.                               |

**Phase 1 outcome (what actually shipped).** The plan above (extend the shared otel-collector daemonset with a remote-write bridge) failed twice in dev: the daemonset image predated the `prometheusremotewrite` receiver, and vmagent speaks Remote Write 1.0 while the receiver only accepts 2.0, a hard protocol incompatibility. charts#11808 was reverted (#12233) and its follow-ups closed. The replacement is a dedicated single-replica **`metrics-bridge`** scrape collector (prometheus receiver, annotation-discovered targets, OTLP export to capture-logs): charts#12239 (dev, merged 2026-06-17), charts#12440 (prod-us + prod-eu, merged 2026-06-25), charts#12493 (scrape memory bound). **INFRA-B (internal-infra quota exemption) was never implemented** and remains an open decision; `MetricsRateLimiterService` has no exemption path today.

### Phase 2 — Query layer (PostHog repo)

| #      | Repo    | PR                                                                                                                                                                              | Notes                                                                        |
| ------ | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| **P3** | posthog | Label filters (`eq`, `neq`, `regex`) on a single clause with explicit `scope: resource \| attribute \| auto`. Uses `attribute_field()` from P0.                                 | First feature flag that requires real data — INFRA-A is the source.          |
| **P4** | posthog | `group_by` on a single clause, with a fixed interval grid shared by every series in the response.                                                                               | Interval is on `MetricQueryRequest`, not per clause (single-grid invariant). |
| **P5** | posthog | `rate` + `increase` aggregations. `runningDifference()` + `clamp_min(..., 0)` for counter-reset handling. Consumes `aggregation_temporality` to skip the diff for delta inputs. | Most panels are rate-based — getting this wrong shows up in every dashboard. |
| **P6** | posthog | `histogram_quantile`. Bounds-equality check inside a group; mismatches drop with a logged warning. Uses `histogram_bounds` / `histogram_counts` arrays from `metrics1`.         | P95 latency panel + every histogram-based SLO.                               |
| **P7** | posthog | Multi-clause query + server-side HogQL formula. Per-clause result joined on time bucket; formula evaluated against named clauses (`(a - b) / a`).                               | Server-side only — no client-side alignment.                                 |

### Phase 3 — Viewer + widget (PostHog repo)

> **Status:** P8 shipped (multi-series chart + label filters + group-by; also a stat mode with anomaly baseline). P9 is half-shipped: the group-by selector exists, the formula expression input does not.
> **P10-P13 are superseded as written.** The dashboards platform now forbids chart-primary widget types (`products/dashboards/CONTRIBUTING.md`: charts/trends on a dashboard go on insight tiles, widgets are for product-native lists). See "Phase 3 (revised)" below; the original rows are kept for the record.

| #       | Repo    | PR                                                                                                                                                                                                              | Notes                                                                                              |
| ------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **P8**  | posthog | `MetricsViewer` — multi-series chart rendering, label-filter UI (consumes the P2 contract).                                                                                                                     | First UI delivery — every later UI consumes the same code path.                                    |
| **P9**  | posthog | `MetricsViewer` — group-by selector + formula expression input.                                                                                                                                                 | Full Viewer parity.                                                                                |
| **P10** | posthog | `metric_timeseries` widget registry entry (`validate_config`, `query_fn`) reusing the metrics facade. Add to `WIDGET_REGISTRY` and `EXPECTED_WIDGET_TYPES` in `products/dashboards/backend/widget_registry.py`. | No new facade method allowed — if the widget reaches for one, the gap is in the viewer's exercise. |
| **P11** | posthog | `metric_timeseries` widget frontend — WidgetCard + catalog entry + config form.                                                                                                                                 | Widget lives in dashboards UI.                                                                     |
| **P12** | posthog | Dashboard variables / filters → metric widget filter injection (`$service`-equivalent).                                                                                                                         | Replicates the Grafana variable UX.                                                                |
| **P13** | posthog | PostHog Annotations rendered as vertical lines on metric widgets.                                                                                                                                               | Replaces Grafana's "Deploys" annotation.                                                           |

### Phase 3 (revised) — metrics on dashboards as insight tiles

The widget path is closed, and the insight path is both sanctioned and cheaper: insights get dashboards, per-tile filter overrides, refresh/caching, sharing, subscriptions, and the alerts product for free. Precedent: logs registered `NodeKind.LogsQuery` + a runner in `posthog/hogql_queries/query_runner.py`, making it renderable through the generic `Query` component.

| #        | PR                                                                                                                                                                    | Notes                                                                                               |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **P10r** | `MetricsQuery` node kind in the schema; runner delegates to the existing `run_metric_query` facade (no new facade method).                                            | Same "no new facade method" rule as the original P10.                                               |
| **P11r** | `Query.tsx` dispatch branch rendering the existing `MetricsViewer` chart components; "Save as insight" from the Viewer; insight lands on dashboards as a normal tile. | Interim escape hatch already works today: SQL-tab HogQL saved as a `DataVisualizationNode` insight. |
| **P12r** | Dashboard variables / filters propagate into `MetricsQuery` tiles (the `$service` equivalent).                                                                        | Today HogQL insight variables only bind to SQL tiles.                                               |
| **P13r** | PostHog Annotations rendered as vertical lines on metric charts.                                                                                                      | The `AnnotationsOverlay` currently wires into Trends rendering only.                                |

### Out of stack (separate plans)

- Streams-table schema rewrite — large project, the `attribute_field()` seam is the entry point.
- prom-compat (Track A) — see `docs/internal/prom-compat/design.md`.
- `prom-client` → OTel SDK swap in PostHog services.
- Deploy annotation automation from Helm release events.

## Sequencing rules

1. **P0 + P1 land before any infra PR.** Real data should not hit `metrics1` at scale before the storage seam (`attribute_field`) and the contract dataclasses are merged — once data exists, you can't undo it cheaply.
2. **INFRA-A..C land between P2 and P3.** P3+ tests run against dev `metrics1` with real OTLP-ingested rows, not synthetic ones, to catch resource-vs-attribute bugs that fixtures miss.
3. **INFRA-A and INFRA-E are different PRs on purpose.** Narrow scrape in dev first; broad scrape only after the query layer can handle it. Resist the temptation to merge them "to save a PR" — that's how storage bloats 5-10× before the schema rewrite lands.
4. **Dashboard-tile PRs (P10r+) must not introduce any new facade method.** If you reach for one, the gap is in the viewer's exercise of the contract — go fix it in P3-P9.

## Local verification path

`hogli dev:setup` → select **`metrics`** intent (`devenv/intent-map.yaml`). This boots `capture-logs`, `ingestion-metrics`, and the dependencies. `metrics1` is created by the standard CH bootstrap. `bin/verify-metrics-pipe` checks end-to-end arrival.

Per-PR sanity checks:

- **P0–P2**: `hogli test products/metrics/backend/tests/` + `curl POST /api/projects/2/metrics/query` (new shape). HogQL SQL tab in `/metrics` works against `posthog.metrics` from day one.
- **P3–P7**: curl + JSON. UI does not show new features until P8/P9.
- **P8+**: browser at `/metrics` (alpha flag on).
- **P11r+**: browser at `/dashboard/...` — save a Viewer query as an insight and add it as a tile.

Seeder script for ad-hoc dev data (no PRs needed):

```bash
clickhouse-client -h localhost --query "
INSERT INTO metrics1 (uuid, team_id, timestamp, service_name, metric_name, metric_type, value, attributes_map_str, resource_attributes)
SELECT generateUUIDv4(), 2, now() - INTERVAL number SECOND, 'capture-logs', 'envoy_5xx_total', 'sum',
       toFloat64(number * 0.1),
       map('container_str', 'capture-logs', 'envoy_response_code_class_str', '5'),
       map('namespace', 'posthog')
FROM numbers(3600)"
```

## Known footguns the stack pre-empts

- Two-grid formulas → P1's `MetricQueryRequest` enforces a single interval shared by every clause.
- Naive `rate()` over a pod restart → P5 uses `clamp_min(runningDifference(value), 0)`.
- Histogram aggregation across mismatched bounds → P6 validates bounds equality within a group.
- `attributes_map_str['foo']` everywhere → P0's `attribute_field()` helper is the only call site.
- Two response shapes (single vs multi series) → P2 returns `[MetricSeries]` from day one, length-1 if no group-by.
- Quota throttling on internal infra traffic → INFRA-B carves an exemption.
- Scraping the whole namespace → INFRA-A scopes to the exact targets the dashboard needs.
- Cumulative vs delta confusion → `aggregation_temporality` checked in P5 before applying `runningDifference`.

## Open decisions — resolved

1. **Internal-infra project** — decided against a dedicated project: scraped cluster metrics land in PostHog's internal project in each environment (local dev uses the local demo project). The quota half of this decision is still open because INFRA-B never shipped (see Phase 1 outcome).
2. **Naming convention** — decided: keep-as-emitted. Prometheus `snake_case_total` for scraped metrics, OTel dotted names for SDK-emitted metrics; do not rewrite either.
3. **Token sensitivity** — resolved: bridge tokens are project capture tokens, not personal API keys. Dev keeps the token inline in charts values (matching the daemonset's existing exporters); prod syncs it via external-secrets.
