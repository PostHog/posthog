---
name: instrumenting-first-party-metrics
description: "How to instrument PostHog's own Metrics product from PostHog-owned code — record counters, gauges, and histograms that land in posthog.metrics, the same way customers do. Use when adding application metrics in this monorepo (web, Celery, Temporal), when asked to push or ship metrics into posthog metrics, or when unsure whether the SDK in this environment supports posthog.metrics yet. Covers the environment decision (SDK-first per the public docs, OTel fallback when the SDK path is not available), the exact version gates per SDK, what is already wired internally, and how to validate metrics actually arrive."
---

# Instrumenting first-party metrics

Goal: get application metrics from PostHog's own code into the **PostHog Metrics product** (`posthog.metrics` table, Metrics UI), the same way customers do.
Follow the [public docs](https://posthog.com/docs/metrics/installation) wherever possible; use OTel only as the fallback when the SDK path isn't available in your environment.
Never invent env vars or hand-roll OTel providers — every environment below already has a working path.

## Step 1 — identify the environment and pick the path

| Where you are                                          | First choice                                                                                           | Fallback                                                                                                 |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| Monorepo Python (web, Celery, Temporal)                | SDK: `posthoganalytics.default_client.metrics` — IF the pinned version supports it (see version gates) | `OtelInstrumentFactory` in `posthog/otel_metrics.py`                                                     |
| Monorepo Node services (`nodejs/`)                     | — (services don't run posthog-node)                                                                    | internal twin: `nodejs/src/common/metrics/otel-metrics.ts`                                               |
| PostHog-owned standalone service / script / other repo | SDK per public docs: `posthog.metrics.count/gauge/histogram`                                           | OTLP env vars per docs (`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=<host>/i/v1/metrics`, Bearer project token) |

> [!WARNING]
> **In a Temporal worker the OTel fallback is not a fallback — it is silence.** `OTEL_METRICS_EXPORT_URL`/`_TOKEN` are set on the web deployment, not on the worker deployments, so `OtelInstrumentFactory` binds a no-op meter there and every twin is dropped.
> No metric recorded through the factory from a worker activity has ever reached the Metrics product, while SDK-path metrics from the same pods do.
> From a worker, use the SDK path or the Temporal metric meter.
>
> Do not assume the `prometheus_client` half of a twin covers for the dropped twin, and do not drop the instrument either.
> `create_worker` starts `CombinedMetricsServer` by default (`enable_combined_metrics_server=True`, from `TEMPORAL_COMBINED_METRICS_SERVER_ENABLED`), and that server serves the Python registry next to the Temporal SDK's own metrics on the worker's metrics port.
> So the registry is exported by default, but it reaches Grafana only if the combined server is still enabled and the deployment scrapes that endpoint.
> Both are deployment configuration outside this repository, so confirm them before you rely on a `prometheus_client` instrument as a worker's only sink.

## Step 2 — check the version gate (don't assume)

`posthog.metrics` shipped in: **posthog-python 7.23.0** (`posthoganalytics` is the same package renamed), **posthog-node 5.43.0**, **posthog-js ~1.399.0** (runtime check: `typeof posthog.metrics?.count === 'function'`).

- Monorepo: `grep posthoganalytics pyproject.toml` and compare against 7.23.0. Below the gate → use the OTel fallback until the bump lands.
- The monorepo is bump-ready: `apps.py` sets the module-level metrics config (service name/version/environment) and Celery's `worker_process_shutdown` flushes the final window, both inert on pre-7.23 versions. Once `posthoganalytics>=7.23` is pinned, the SDK path works from web and Celery with no further app changes.
- Elsewhere: check the lockfile/requirements against the versions above; upgrade rather than work around.

## Step 3 — instrument (keep it doc-shaped)

**SDK path** (mirrors the public docs exactly):

```python
client.metrics.count("invoices.processed", 1, attributes={"plan": "pro"})
client.metrics.gauge("queue.depth", 42)
client.metrics.histogram("job.duration", 187, unit="ms")
```

- In the monorepo (post-bump) the client is `posthoganalytics.default_client` — config and flush hooks are already wired; just record.
- Short-lived processes and recycling workers must flush (`client.metrics.flush()`); the monorepo Celery hook already does this.
- Set a service name (monorepo: already configured from `OTEL_SERVICE_NAME`, fallback `posthog`); it's how the Metrics UI filters.

**OTel fallback in the monorepo** — `posthog/otel_metrics.py`, zero setup by the caller:

```python
from posthog.otel_metrics import OtelInstrumentFactory

_otel = OtelInstrumentFactory("myarea")
_otel.counter("myarea.jobs.processed").add(1, {"outcome": "success"})
_otel.histogram("myarea.job.duration", unit="s").record(1.87, {"queue": "default"})
_otel.gauge("myarea.backlog").set(42)
```

Reference call sites: `products/dashboards/backend/access.py` (smallest, web), `products/managed_warehouse/backend/metrics.py` (SDK path from a Temporal worker).
If a `prometheus_client` instrument already exists at the site and its Grafana series must be kept, mirror it with `record_counter_twin`/`record_histogram_twin`/`record_gauge_twin`/`timed_histogram_twin` instead of a direct instrument — the twin derives name/buckets from it so the sinks can't drift.

**Rules for both paths**: dot-separated stable names (`jobs.processed`, not `metric1`); explicit `unit` on histograms; low-cardinality attributes only (`route`, `status`, `plan` — never user/session/request IDs; `team_id` sparingly and deliberately).

## Step 4 — validate it actually works

1. **Know where it lands.** SDK path in the monorepo → the dogfood US project (token set in `apps.py`). Internal OTel path → whatever project charts' `OTEL_METRICS_EXPORT_TOKEN` points at. These can differ — confirm before building dashboards.
2. **Dev/test gotchas.** In monorepo DEBUG and TEST the default client is `disabled` → the SDK path records nothing locally (by design). `OTEL_METRICS_EXPORT_URL`/`_TOKEN` are unset locally → the OTel factory no-ops. To exercise the pipe for real, use a scratch script with an explicit `Posthog(token, host, metrics={"service_name": "<yourname>-scratch"})` client against a real project, or `bin/verify-metrics-pipe` to check the local collector pipe itself — it only reports the ingestion services' own metrics (`logs-ingestion`/`metrics-ingestion`/`nodejs` service names), never a metric you emit from Python; use the arrival checks below for that.
3. **Observe arrival** (~1 min ingestion lag): MCP `metric-names-list` (search your metric name) then `query-metrics` (counters: `increase`; gauges: `avg`; histograms: `histogram_quantile`), or the Metrics UI name picker, or SQL: `SELECT * FROM posthog.metrics WHERE metric_name = '...' ORDER BY timestamp DESC LIMIT 10`.
4. **Unit tests.** OTel factory twins/instruments swallow errors by design — assert on behavior around them, or use `reset_otel_metrics_for_tests()` + `override_settings` to exercise gating. SDK path: mock the client or assert against `client.metrics._series` state; never hit the network in tests.

## What not to do

- **Don't add env vars.** `OTEL_METRICS_EXPORT_URL`/`_TOKEN` (internal push) are charts-level deployment config; `OTEL_EXPORTER_OTLP_METRICS_*` belongs in external apps only. Unset means safe no-op, not misconfiguration.
- **Don't build `MeterProvider`s/exporters or cache OTel instruments yourself** — `posthog/otel_metrics.py` owns lazy, fork-safe, per-PID provider lifecycle.
- **Don't hand-roll a workaround when the version gate fails** — the fix is the dependency bump (wiring is pre-landed), or the OTel factory in the meantime.

## Adjacent (not this skill's job)

Grafana dashboards via scraped `prometheus_client` instruments (port 8001, always-on), and `pushed_metrics_registry`/`PushGatewayTask` for one-shot batch jobs (`PROM_PUSHGATEWAY_ADDRESS`), still exist and keep working — this skill is about the Metrics product.
Keep a prom instrument (with a twin) only when an existing Grafana dashboard depends on it.
