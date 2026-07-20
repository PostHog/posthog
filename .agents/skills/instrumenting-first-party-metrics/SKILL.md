---
name: instrumenting-first-party-metrics
description: 'How to emit first-party metrics from PostHog backend code (Django web, Celery, Temporal) so they reach both Grafana and the PostHog Metrics product. Use when adding a Prometheus counter, gauge, or histogram, when asked to push or ship metrics into PostHog metrics, or when tempted to add OTel SDK setup or metrics env vars to app code. Covers the prometheus_client + OtelInstrumentFactory twin pattern, what is already wired (scraping, multiprocess mode, OTLP push gating), and what not to touch.'
---

# Instrumenting first-party metrics

## When to use this

You're adding a metric to PostHog's own backend code — counting task outcomes, timing an operation, gauging a backlog — and you want it visible in Grafana, the PostHog Metrics product, or both. Also read this before concluding that new env vars, OTel SDK setup, or exporter wiring are needed: they aren't.

This is for code in this repo. To instrument a customer's app (or any external codebase), that's the `posthog.metrics` SDK API and OTLP endpoint described in the [public metrics docs](https://posthog.com/docs/metrics/installation) — do not use those approaches here.

## Two sinks, one declaration

Every metric here has up to two destinations:

1. **Grafana** — a plain `prometheus_client` `Counter`/`Gauge`/`Histogram`, scraped from the process. Always works, zero wiring.
2. **PostHog Metrics product** — an OTLP "twin" pushed through `posthog/otel_metrics.py` to our own ingest. Opt-in per call site, one extra line.

Declare the Prometheus instrument module-level, next to the code that emits it (see the `posthog/metrics.py` docstring — only shared label constants live centrally):

```python
from prometheus_client import Counter

JOBS_PROCESSED_COUNTER = Counter(
    "posthog_myarea_jobs_processed",
    "Jobs processed by my area's worker.",
    labelnames=["outcome"],
)
```

## Scraping is already wired — touch nothing

- **Web**: Nginx Unit / Granian serve aggregated metrics on port 8001 (`bin/unit_metrics.py`, `bin/granian_metrics.py`).
- **Celery**: each worker exposes port 8001 via the `worker_process_init` handler in `posthog/celery.py`.
- **Multiprocess mode**: `PROMETHEUS_MULTIPROC_DIR` is exported by `bin/docker-server-unit` and `bin/docker-worker-celery`.

A new instrument on the default registry is picked up automatically. No env var, no registration, no per-metric config.

## Reaching the Metrics product: the twin pattern

Declare one factory per area, module-level, and record a twin beside each Prometheus update:

```python
from posthog.otel_metrics import OtelInstrumentFactory

_otel = OtelInstrumentFactory("myarea")

def process_job(...):
    JOBS_PROCESSED_COUNTER.labels(outcome="success").inc()
    _otel.record_counter_twin(JOBS_PROCESSED_COUNTER, 1, {"outcome": "success"})
```

The twin derives its name, description, and histogram buckets from the Prometheus instrument, so the two sinks can't drift. Available: `record_counter_twin`, `record_histogram_twin`, `record_gauge_twin`, and `timed_histogram_twin` (a context manager that times a block into both sinks at once).

For a new metric that only needs the Metrics product (no Grafana dashboard), use the factory's direct instruments instead of a twin: `_otel.counter(name).add(...)`, `_otel.histogram(name).record(...)`, `_otel.gauge(name).set(...)`.

Reference call sites, simplest to fullest:

- `products/dashboards/backend/access.py` — one counter twin, minimal setup
- `posthog/session_recordings/session_recording_api.py` — `timed_histogram_twin` around blob fetches
- `products/replay_vision/backend/temporal/metrics.py` — a full product metrics module (Temporal context)

## What not to do

- **Don't set env vars.** `OTEL_METRICS_EXPORT_URL` and `OTEL_METRICS_EXPORT_TOKEN` gate the OTLP push, but they're per-deployment charts config. Unset (as in local dev and self-hosted), the factory records into a no-op meter — free and safe. Nothing to add to `.env`, settings defaults, or docker-compose.
- **Don't build providers or exporters.** `posthog/otel_metrics.py` handles lazy, per-PID (fork-safe) provider init and keeps the OTel SDK off the `django.setup()` path. Adding `MeterProvider`/`PeriodicExportingMetricReader` setup anywhere else duplicates it wrongly.
- **Don't create OTel instruments at import time or cache them yourself.** They'd bind to the no-op meter forever. The factory caches per-process and rebuilds after forks.
- **Don't use the customer-facing path here.** No `posthog.metrics` SDK calls, no `OTEL_EXPORTER_OTLP_METRICS_*` env vars — that's for external apps.
- **Don't attach high-cardinality labels.** Every unique label combination is a series in both sinks. `team_id` is used sparingly and deliberately; user/session/request IDs never.

## Adjacent mechanisms

- **Short-lived batch jobs** (a metric emitted once per run, no live process to scrape): `pushed_metrics_registry` / `PushGatewayTask` in `posthog/metrics.py` and `posthog/tasks/utils.py`, gated on `PROM_PUSHGATEWAY_ADDRESS`. Prefer the twin pattern for anything running inside web/celery/temporal workers.
- **Node services**: `nodejs/src/common/metrics/otel-metrics.ts` is the TypeScript twin of `posthog/otel_metrics.py` and shares the same env-var pair.

## Verifying

- **Unit tests**: assert on the Prometheus instrument (twins swallow all errors by design, so they can't be asserted through failures). To exercise the OTLP gating itself, use `reset_otel_metrics_for_tests()` with `override_settings`.
- **End to end locally**: `bin/verify-metrics-pipe` exercises the local pipe; `otel-collector-config.dev.yaml` shows the dev collector setup.
- **Naming note**: `prometheus_client` strips `_total` from counter names internally and re-appends it on scrape; twins restore it, so the same name appears in Grafana and the Metrics product.
