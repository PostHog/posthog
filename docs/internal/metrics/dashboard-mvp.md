# Metrics Dashboard MVP — Replacing the Grafana logs.json inside PostHog

**Status:** design — owners @daniel-v, #team-apm (@jonmcwest, @frankh).
**Sibling docs:** [`docs/internal/prom-compat/design.md`](../prom-compat/design.md) (read plane for Prometheus ecosystem — out of scope here).

## Why

The cluster's `logs.json` Grafana dashboard (≈60 panels, source: `PostHog/grafana-dashboards/logs.json`) is the on-call surface for the logs / traces / metrics ingestion stack.
We already store metrics natively in `metrics1` on the logs ClickHouse cluster.
This doc scopes the work to render that exact dashboard inside PostHog (`/dashboard/...`) against `posthog.metrics`, so on-call can leave Grafana behind.

Native PostHog Metrics stays the user-facing product. The Prometheus-ecosystem read plane (`services/prom-compat/`, Track A) is a separate stack reading the same storage.

## Non-goals (deliberately deferred)

1. Schema rewrite to the streams-table pattern (Snuffle benchmarks: ~10× disk on metrics, ~5× on logs).
   The seam for that rewrite is the `attribute_field()` helper introduced in P0.
2. PromQL / `prom-compat` service — separate stack, already designed.
3. SDK swap (replacing `prom-client` in `nodejs/src/...` with OTel SDK).
4. Deploy-annotation automation from Helm release events.

## What's already in place (do not re-build)

**Ingest data plane** — shipped or in-flight:

- `rust/capture-logs/`: OTLP/HTTP receiver at `/v1/metrics` (and `/i/v1/metrics`), JSON or protobuf, writes to Kafka. `rust/capture-logs/src/main.rs:154-160`, `src/service.rs:703-820`.
- `nodejs/src/metrics-ingestion/metrics-ingestion-consumer.ts`: drains Kafka into ClickHouse with quota + ratelimit (`MetricsRateLimiterService`).
- ClickHouse `metrics1` table (OTel-shaped, gauge / sum / histogram / exp-histogram / summary), MVs into `metric_attributes`. `posthog/clickhouse/metrics/metrics1.py`. Registered in `posthog/clickhouse/schema.py:332-333`.
- `charts` (in-flight `daniel/metrics-prod-rollout`): WarpStream metrics cluster + `kafka.metricsBrokers` on capture-logs + `/i/v1/metrics` Contour ingress + `metrics-ingestion` deployment, prod-us + prod-eu.
- `posthog-cloud-infra`#8321/8322/8415/8434/8489 (merged): Kafka topics + S3 bucket + IRSA + CH named collection + Postgres app user.
- `argocd/otel-collector/` (daemonset, already deployed): an existing OTel Collector with `prometheus` + `otlp` receivers and a `metrics` pipeline whose exporter today is `debug`.

**Product surface — alpha (gated by `FEATURE_FLAGS.METRICS`):**

- `products/metrics/backend/facade/api.py`: `team_has_metrics(team)`, `query_metric(team, metric_name, aggregation, date_from, date_to)`, `list_metric_names(team, search, limit)`.
- `products/metrics/backend/metric_query_runner.py`: single-metric runner, aggregations `sum | avg | count | p95`, auto-bucketed to ~60 points.
- `products/metrics/frontend/MetricsScene.tsx`: Viewer tab (single-metric) + HogQL SQL editor over `posthog.metrics`.

## Gap to close

|                       | Today                            | Target                                                                               |
| --------------------- | -------------------------------- | ------------------------------------------------------------------------------------ |
| Filters               | none (metric name + agg only)    | label / attribute predicates with explicit scope (`resource` / `attribute` / `auto`) |
| Group-by              | none                             | shared interval grid, multi-series response                                          |
| Aggregations          | sum / avg / count / p95          | + `rate`, `increase`, `histogram_quantile`                                           |
| Multi-metric          | one clause                       | N clauses + server-side HogQL formula                                                |
| Storage seam          | direct `attributes_map_str[...]` | `attribute_field(name)` helper used everywhere                                       |
| Wire shape            | `[{time, value}]`                | `[{labels, points}]` — stable from PR2                                               |
| Dashboard widget      | none                             | `metric_timeseries` widget type                                                      |
| Dashboard variables   | n/a                              | dashboard filters propagate into widget config                                       |
| Annotations           | n/a                              | PostHog Annotations render as vertical lines on metric widgets                       |
| Scraped infra metrics | not flowing                      | existing collector's metrics pipeline exports to capture-logs                        |
| MCP                   | none                             | follow-on, not in this MVP                                                           |

## Architecture (target)

```text
[ envoy /stats/prometheus       ]                  [ posthog services /metrics ]
[ kminion /metrics              ]   ──scrape──>    [ otel-collector daemonset  ]   ──OTLP/HTTP──>   capture-logs /i/v1/metrics
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

### Phase 2 — Query layer (PostHog repo)

| #      | Repo    | PR                                                                                                                                                                              | Notes                                                                        |
| ------ | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| **P3** | posthog | Label filters (`eq`, `neq`, `regex`) on a single clause with explicit `scope: resource \| attribute \| auto`. Uses `attribute_field()` from P0.                                 | First feature flag that requires real data — INFRA-A is the source.          |
| **P4** | posthog | `group_by` on a single clause, with a fixed interval grid shared by every series in the response.                                                                               | Interval is on `MetricQueryRequest`, not per clause (single-grid invariant). |
| **P5** | posthog | `rate` + `increase` aggregations. `runningDifference()` + `clamp_min(..., 0)` for counter-reset handling. Consumes `aggregation_temporality` to skip the diff for delta inputs. | Most panels are rate-based — getting this wrong shows up in every dashboard. |
| **P6** | posthog | `histogram_quantile`. Bounds-equality check inside a group; mismatches drop with a logged warning. Uses `histogram_bounds` / `histogram_counts` arrays from `metrics1`.         | P95 latency panel + every histogram-based SLO.                               |
| **P7** | posthog | Multi-clause query + server-side HogQL formula. Per-clause result joined on time bucket; formula evaluated against named clauses (`(a - b) / a`).                               | Server-side only — no client-side alignment.                                 |

### Phase 3 — Viewer + widget (PostHog repo)

| #       | Repo    | PR                                                                                                                                                                                                              | Notes                                                                                              |
| ------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **P8**  | posthog | `MetricsViewer` — multi-series chart rendering, label-filter UI (consumes the P2 contract).                                                                                                                     | First UI delivery — every later UI consumes the same code path.                                    |
| **P9**  | posthog | `MetricsViewer` — group-by selector + formula expression input.                                                                                                                                                 | Full Viewer parity.                                                                                |
| **P10** | posthog | `metric_timeseries` widget registry entry (`validate_config`, `query_fn`) reusing the metrics facade. Add to `WIDGET_REGISTRY` and `EXPECTED_WIDGET_TYPES` in `products/dashboards/backend/widget_registry.py`. | No new facade method allowed — if the widget reaches for one, the gap is in the viewer's exercise. |
| **P11** | posthog | `metric_timeseries` widget frontend — WidgetCard + catalog entry + config form.                                                                                                                                 | Widget lives in dashboards UI.                                                                     |
| **P12** | posthog | Dashboard variables / filters → metric widget filter injection (`$service`-equivalent).                                                                                                                         | Replicates the Grafana variable UX.                                                                |
| **P13** | posthog | PostHog Annotations rendered as vertical lines on metric widgets.                                                                                                                                               | Replaces Grafana's "Deploys" annotation.                                                           |

### Out of stack (separate plans)

- Streams-table schema rewrite — large project, the `attribute_field()` seam is the entry point.
- prom-compat (Track A) — see `docs/internal/prom-compat/design.md`.
- `prom-client` → OTel SDK swap in PostHog services.
- Deploy annotation automation from Helm release events.

## Sequencing rules

1. **P0 + P1 land before any infra PR.** Real data should not hit `metrics1` at scale before the storage seam (`attribute_field`) and the contract dataclasses are merged — once data exists, you can't undo it cheaply.
2. **INFRA-A..C land between P2 and P3.** P3+ tests run against dev `metrics1` with real OTLP-ingested rows, not synthetic ones, to catch resource-vs-attribute bugs that fixtures miss.
3. **INFRA-A and INFRA-E are different PRs on purpose.** Narrow scrape in dev first; broad scrape only after the query layer can handle it. Resist the temptation to merge them "to save a PR" — that's how storage bloats 5-10× before the schema rewrite lands.
4. **Widget PRs (P10+) must not introduce any new facade method.** If you reach for one, the gap is in the viewer's exercise of the contract — go fix it in P3-P9.

## Local verification path

`hogli dev:setup` → select **`metrics`** intent (`devenv/intent-map.yaml:99-101`). This boots `capture-logs`, `ingestion-metrics`, and the dependencies. `metrics1` is created by the standard CH bootstrap.

Per-PR sanity checks:

- **P0–P2**: `hogli test products/metrics/backend/tests/` + `curl POST /api/projects/2/metrics/query` (new shape). HogQL SQL tab in `/metrics` works against `posthog.metrics` from day one.
- **P3–P7**: curl + JSON. UI does not show new features until P8/P9.
- **P8+**: browser at `/metrics` (alpha flag on).
- **P11+**: browser at `/dashboard/...` — add a `metric_timeseries` tile.

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

## Open decisions (need owner input)

1. **Internal-infra project** — which project receives scraped cluster metrics in each environment? Recommend a dedicated `posthog-internal-infra` project with its own `team_id` so `team_has_metrics` doesn't flip on the dogfood project. Cap budget separately from customer billing.
2. **Naming convention** — keep Prometheus `snake_case_total` for scraped metrics (preserves dashboard expressions) and use OTel dotted (`http.server.duration`) for new SDK-emitted metrics. Document; do not mix.
3. **Token sensitivity** — existing `argocd/otel-collector/values/values.dev.yaml` exposes `Bearer sTMFPsFhdP1Ssg` in plain YAML for the traces pipeline. Confirm: that's a project public capture token, not a personal API key. Apply the same model to the new `otlphttp/posthog-metrics` exporter.
