# Metrics — deployment layout (local / dev / prod-us / prod-eu / charts)

Companion to [`dashboard-mvp.md`](./dashboard-mvp.md). This is the "what has to exist where" checklist for metrics to be fully functional, plus the schema decision.

## Schema decision (settled)

**Alpha ships on the current `metrics1` table.** The streams-table layout (Snuffle's default schema: `metrics_series` id→labels + `metrics_samples` id,ts,value + inverted `metrics_label_index`) is the **post-alpha storage track**, not a blocker.

Why this is safe and correct for a days-to-alpha timeline:

- Snuffle's `create_metrics_posthog_schema.sql` is **our current `metrics1` verbatim** — Rory built his PromQL bridge to read our existing table. So prom-compat works against `metrics1` as-is; we lose nothing by not migrating first.
- The streams layout is the _eventual_ target (Snuffle benchmarks ~89.5% less disk, ~31→3 bytes/sample) but it changes the ingestion write path + adds a backfill — too much risk to land under an alpha deadline.
- The `attribute_field()` helper (P0) is the migration seam: when storage moves to streams, only that one function changes, not every query call site.

**Action when we do the storage track:** model `metrics_series` keyed by a full series fingerprint — Snuffle computes it as `cityHash64(metric_name, service_name, mapSort(resource_attributes), mapSort(attributes_map_str))`. We already materialize a partial `resource_fingerprint = cityHash64(resource_attributes)` on `metrics1`; the full series identity adds metric_name + service_name + sorted data-point attributes.

## The full data path (all environments)

```text
producers ─► capture-logs /i/v1/metrics ─► Kafka (WarpStream "metrics") ─► metrics-ingestion consumer ─► ClickHouse metrics1 (logs cluster)
   │                                                                                                              │
   ├─ app SDKs (OTLP, customer traffic)                                                                           ▼
   └─ infra/service metrics via vmagent ─► otel-collector bridge (prometheusremotewrite→OTLP)         products/metrics (HogQL) + prom-compat (PromQL)
```

Two producer classes:

1. **Customer OTLP** — apps push OTLP straight to `/i/v1/metrics`. Already works in every env where the ingest path is live.
2. **Our own infra/service metrics** — vmagent already scrapes them; the otel-collector bridge (INFRA-A) fans a copy into `/i/v1/metrics`. This is the "pipe our logs services through" path.

## Status matrix — what exists where

Legend: ✅ live · ⏳ in-flight (PR) · ➕ this stack adds it · — n/a

| Layer                                                    | local             | dev               | prod-us       | prod-eu       | Where it lives                                 |
| -------------------------------------------------------- | ----------------- | ----------------- | ------------- | ------------- | ---------------------------------------------- |
| Kafka topics (`ingestion_metrics`, `clickhouse_metrics`) | ✅ (compose)      | ✅                | ✅            | ✅            | cloud-infra #8321                              |
| WarpStream metrics cluster + S3 + IRSA                   | —                 | ✅                | ⏳            | ⏳            | charts `warpstream-metrics`; cloud-infra #8322 |
| CH named collection `warpstream_metrics`                 | —                 | ✅                | ✅            | ✅            | cloud-infra #8415/#8489                        |
| metrics-ingestion Postgres app user                      | ✅                | ✅                | ✅            | ✅            | cloud-infra #8434                              |
| capture-logs `kafka.metricsBrokers`/`metricsTopic`       | ✅ (compose)      | ✅                | ⏳            | ⏳            | charts `capture-logs` (global in rollout)      |
| Contour ingress `/i/v1/metrics`                          | ✅ (caddy)        | ✅                | ⏳            | ⏳            | charts `contour-ingress`                       |
| metrics-ingestion consumer deploy                        | ✅ (mprocs)       | ✅                | ⏳            | ⏳            | charts `logs/metrics-ingestion`                |
| ClickHouse `metrics1` + MVs                              | ✅ (CH bootstrap) | ✅                | ⏳ direct SQL | ⏳ direct SQL | `posthog/clickhouse/metrics/`                  |
| **otel-collector bridge** (infra→metrics1)               | ➕ local recipe   | ➕ INFRA-A #11808 | ➕ INFRA-D    | ➕ INFRA-D    | charts `otel-collector` + `vmagent`            |
| Rate-limit/quota exemption for internal-infra token      | —                 | ➕ INFRA-B        | ➕ INFRA-D    | ➕ INFRA-D    | `nodejs/.../metrics-rate-limiter.service.ts`   |
| Feature flag `METRICS` + `metrics:read` scope            | ✅ code           | ✅ code           | ✅ code       | ✅ code       | posthog repo (all envs share)                  |
| Query layer (filters/group-by/rate/hist/formula)         | ➕ this stack     | ➕                | ➕            | ➕            | `products/metrics/backend`                     |

**Read:** the ingestion data plane is **done in dev**, and **pending in prod** behind `daniel/metrics-prod-rollout` (charts) + the post-merge `metrics1` SQL apply on the prod-us/prod-eu logs CH clusters. cloud-infra scaffolding (topics/S3/IRSA/CH collection/PG user) is **merged in all three envs**.

## What still has to be added, by repo

### posthog (this stack)

- Query layer: `MetricQueryRequest`/`MetricSeries` contracts → endpoint → shared metric-math library (filters, group-by, rate, increase, histogram_quantile, formula). **This is the product gap; nothing else replaces it.**
- INFRA-B: internal-infra token quota exemption in `MetricsRateLimiterService`.
- (Post-alpha) Alerting on the shared math library; streams-table storage migration.

### charts

- INFRA-A (#11808, dev): otel-collector `prometheusremotewrite` bridge + vmagent second remote-write. **Draft up.**
- INFRA-C (dev): drop the `debug` exporter once metrics1 arrival is confirmed.
- INFRA-D (prod-us + prod-eu): replicate the bridge after `metrics-prod-rollout` merges and prod `metrics1` SQL is applied. Decide internal-infra project here.
- INFRA-E: broaden the bridge filter beyond the initial dashboard metric set once the query layer can render more.
- (Merge) `daniel/metrics-prod-rollout`: takes the ingestion data plane to prod-us + prod-eu.

### posthog-cloud-infra

- **Nothing new required** for alpha — topics/S3/IRSA/CH collection/PG user are all merged in every env.
- Open decision (INFRA-D): provision a dedicated `posthog-internal-infra` project + token per env so scraped infra metrics don't flip `team_has_metrics` on the dogfood team and so internal-infra volume is billed/quota'd separately.

### Per-env "go live" checklist for prod

1. Merge `daniel/metrics-prod-rollout` (charts).
2. Apply `metrics1` + MV DDL to prod-us and prod-eu logs CH clusters (direct SQL, as in dev).
3. Point a smoke OTLP producer at the prod `/i/v1/metrics`; confirm rows in `metrics1`.
4. Land INFRA-D (bridge) per env; confirm vmagent → bridge → metrics1 for the dashboard metric set.
5. Verify `team_has_metrics` + the query layer against real prod series.

## Local validation (the priority) — fully functional metrics on a laptop

No charts/cloud-infra needed locally. The `metrics` dev intent boots the whole pipe, and the dev `otel-collector` container **already scrapes our logs services and pushes them into `metrics1`** — no manual collector to run.

1. `hogli dev:setup` → select the **`metrics`** intent (boots `capture-logs`, `ingestion-metrics`, `ingestion-logs`, the dev `otel-collector`, deps; `metrics1` created by CH bootstrap). `hogli start`.
2. Enable the `metrics` feature flag for your user.
3. Real PostHog logs services pipe through automatically: the dev collector (`otel-collector-config.dev.yaml`) scrapes `/_metrics` on `logs-ingestion` (`:6743`), `metrics-ingestion` (`:6744`), and the plugin server (`:6738`) every 15s and exports OTLP to `capture-logs` (token `phc_local` → team*id 1). Their `prom-client` counters (`logs_ingestion*_`, `metrics*ingestion*_`, consumer lag, batch utilization) are exactly the Grafana logs-dashboard metrics.
4. Validate:
   - `bin/verify-metrics-pipe` — checks `metrics1` for the piped service metrics and prints what arrived (pass/fail with troubleshooting).
   - `/metrics` SQL tab: `SELECT metric_name, count() FROM posthog.metrics WHERE service_name = 'logs-ingestion' GROUP BY 1 ORDER BY 2 DESC` (note: data lands on **team_id 1** via `phc_local`).
   - `/metrics` Viewer: the query layer (filters/group-by/rate/histogram_quantile) against the same data.

Ad-hoc seed without the pipe (no PRs needed):

```bash
clickhouse-client -h localhost --query "
INSERT INTO metrics1 (uuid, team_id, timestamp, service_name, metric_name, metric_type, value, attributes_map_str, resource_attributes)
SELECT generateUUIDv4(), 2, now() - INTERVAL number SECOND, 'logs-ingestion', 'logs_ingestion_bytes_received_total', 'sum',
       toFloat64(number * 1024),
       map('container_str','logs-ingestion','team_id_str','2'),
       map('namespace','posthog')
FROM numbers(3600)"
```

(`team_has_metrics` caches for 7 days — after wiping CH, `cache.delete("team:2:has_metrics")`.)
