# Metrics — deployment layout (local / dev / prod-us / prod-eu / charts)

Companion to [`dashboard-mvp.md`](./dashboard-mvp.md). This is the "what has to exist where" checklist for metrics to be fully functional, plus the schema decision.

## Schema decision (settled)

**Alpha ships on the current `metrics1` table.** The streams-table layout (Snuffle's default schema: `metrics_series` id→labels + `metrics_samples` id,ts,value + inverted `metrics_label_index`) is the **post-alpha storage track**, not a blocker.

Why this is safe and correct for a days-to-alpha timeline:

- Snuffle's `create_metrics_posthog_schema.sql` is **our current `metrics1` verbatim** — Rory built his PromQL bridge to read our existing table. So prom-compat works against `metrics1` as-is; we lose nothing by not migrating first.
- The streams layout is the _eventual_ target (Snuffle benchmarks ~89.5% less disk, ~31→3 bytes/sample) but it changes the ingestion write path + adds a backfill — too much risk to land under an alpha deadline.
- The `attribute_field()` helper (P0) is the migration seam: when storage moves to streams, only that one function changes, not every query call site.

**Update (2026-07):** the series identity question is settled differently than sketched here. The `metric_series` / `metric_samples` split shipped as the events-model drill-down track (posthog#66163/#66169/#66183, live in prod both regions since 2026-07-02), and the series fingerprint is **assigned at ingest in capture-logs (SipHash-1-3, includes `metric_type`)** rather than computed in ClickHouse with cityHash64 (posthog#67195/#67196). The passthrough MVs drop rows with a NULL fingerprint. `metrics1` remains the pre-aggregated TSDB read path; its streams-table rewrite is still the deferred post-alpha track, with `attribute_field()` as the seam.

## The full data path (all environments)

```text
producers ─► capture-logs /i/v1/metrics ─► Kafka (WarpStream "metrics") ─► metrics-ingestion consumer ─► ClickHouse metrics1 (logs cluster)
   │                                                                                                              │
   ├─ app SDKs (OTLP, customer traffic)                                                                           ▼
   └─ infra/service metrics ─► metrics-bridge scrape collector (prometheus receiver → OTLP)           products/metrics (HogQL) + prom-compat (PromQL)
```

Two producer classes:

1. **Customer OTLP** — apps push OTLP straight to `/i/v1/metrics`. Already works in every env where the ingest path is live.
2. **Our own infra/service metrics** — the dedicated `metrics-bridge` collector scrapes the dashboard targets and pushes OTLP into `/i/v1/metrics`. (The original vmagent remote-write design was scrapped: vmagent only speaks Remote Write 1.0, the OTel receiver only accepts 2.0.)

## Status matrix — what exists where

Legend: ✅ live · ⏳ in-flight (PR) · ➕ this stack adds it · — n/a

| Layer                                                    | local             | dev             | prod-us         | prod-eu         | Where it lives                                                                    |
| -------------------------------------------------------- | ----------------- | --------------- | --------------- | --------------- | --------------------------------------------------------------------------------- |
| Kafka topics (`ingestion_metrics`, `clickhouse_metrics`) | ✅ (compose)      | ✅              | ✅              | ✅              | cloud-infra #8321                                                                 |
| WarpStream metrics cluster + S3 + IRSA                   | —                 | ✅              | ✅              | ✅              | charts `warpstream-metrics`; cloud-infra #8322                                    |
| CH named collection `warpstream_metrics`                 | —                 | ✅              | ✅              | ✅              | cloud-infra #8415/#8489                                                           |
| metrics-ingestion Postgres app user                      | ✅                | ✅              | ✅              | ✅              | cloud-infra #8434                                                                 |
| capture-logs `kafka.metricsBrokers`/`metricsTopic`       | ✅ (compose)      | ✅              | ✅              | ✅              | charts `capture-logs`; rollout charts#11702                                       |
| Contour ingress `/i/v1/metrics`                          | ✅ (caddy)        | ✅              | ✅              | ✅              | charts `contour-ingress`                                                          |
| metrics-ingestion consumer deploy                        | ✅ (mprocs)       | ✅              | ✅              | ✅              | charts `logs/metrics-ingestion`                                                   |
| ClickHouse `metrics1` + MVs + samples/series             | ✅ (CH bootstrap) | ✅              | ✅ direct SQL   | ✅ direct SQL   | `posthog/clickhouse/metrics/`, `bin/clickhouse-metrics.sql`                       |
| **metrics-bridge** scrape collector (infra→metrics1)     | ✅ dev collector  | ✅ charts#12239 | ✅ charts#12440 | ✅ charts#12440 | charts `metrics-bridge` ArgoCD app                                                |
| Rate-limit/quota exemption for internal-infra token      | —                 | ❌ not built    | ❌ not built    | ❌ not built    | `nodejs/src/ingestion/pipelines/metrics/services/metrics-rate-limiter.service.ts` |
| Feature flag `METRICS` + `metrics:read` scope            | ✅ code           | ✅ code         | ✅ code         | ✅ code         | posthog repo (all envs share)                                                     |
| Query layer (filters/group-by/rate/hist/formula)         | ✅ shipped        | ✅              | ✅              | ✅              | `products/metrics/backend`                                                        |

**Read (2026-07-08):** the ingestion data plane is **live end-to-end in dev, prod-us, and prod-eu**, including the events-model tables with ingest-assigned fingerprints (rollout completed 2026-07-02). The two open items are the internal-infra quota exemption (INFRA-B, never built) and retention: `metrics1` and `metric_attributes` still have **no TTL**.

## What still has to be added, by repo

### posthog (this stack)

- ~~Query layer~~ **shipped**: `MetricQueryRequest`/`MetricSeries` contracts, filters, group-by, rate, increase, histogram_quantile, formula, all live behind `POST .../metrics/query/`.
- INFRA-B: internal-infra token quota exemption in `MetricsRateLimiterService`. **Still open, never implemented.**
- Retention: `MODIFY TTL` migration for `metrics1` + `metric_attributes` (use `materialize_ttl_after_modify = 0`). **Still open.**
- (Post-alpha) Alerting on the shared math library; `metrics1` streams-table storage migration; dashboard insight tiles (see `dashboard-mvp.md` Phase 3 revised).

### charts — done

The remote-write bridge plan (INFRA-A/#11808) was reverted after a hard vmagent RW-1.0 vs receiver RW-2.0 protocol incompatibility. What shipped instead: a dedicated `metrics-bridge` scrape collector, dev (charts#12239) and prod-us + prod-eu (charts#12440), with a scrape memory bound (charts#12493). The ingestion data plane reached prod via charts#11702.

### posthog-cloud-infra

- **Nothing new required** for alpha — topics/S3/IRSA/CH collection/PG user are all merged in every env.
- Decision made: scraped infra metrics land in PostHog's internal project per environment (no dedicated project). The separate-quota half of the intent is unmet until INFRA-B ships.

### Per-env "go live" checklist for prod — ✅ completed 2026-07

All five steps are done in both regions: charts rollout merged, `metrics1` + samples/series DDL applied (fingerprint cutover 2026-07-02), smoke OTLP verified, scrape collector live, query layer verified against real prod series.

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
