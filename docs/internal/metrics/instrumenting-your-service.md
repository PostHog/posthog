# Instrumenting your service with PostHog Metrics

The standard recipe for PostHog teams adding metrics to their own services. The goal is that every team instruments the same way, so metrics from any service are named predictably, filterable by the same attributes, and alertable without asking the APM team how.

Dogfood rule: instrument with `posthog.metrics` calls (or plain OTel where an SDK doesn't exist yet). Do **not** stand up a Prometheus registry + bridge inside a service — the collector bridge exists for infra-level metrics we already scrape, not for new application instrumentation.

## Which SDK

| Runtime                          | Use                                         | Status                                                                               |
| -------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------ |
| Browser / web app                | `posthog-js` — `posthog.metrics.*`          | Released                                                                             |
| Node service                     | `posthog-node` — `client.metrics.*`         | In review ([posthog-js#4117](https://github.com/PostHog/posthog-js/pull/4117))       |
| Python (Django, Celery, workers) | `posthog-python` — `client.metrics.*`       | In review ([posthog-python#739](https://github.com/PostHog/posthog-python/pull/739)) |
| Rust / Go / anything else        | OTel SDK → OTLP exporter at `/i/v1/metrics` | Works today ([docs](https://posthog.com/docs/metrics))                               |

All four land in the same store with the same series model; the SDK facades are conveniences over the identical OTLP wire shape.

## Standard setup

One block of config per service, set once where the client is created. The `metrics` client option requires the SDK versions from the table above — on older versions the constructors below fail.

```ts
// Node
const client = new PostHog(process.env.POSTHOG_PROJECT_TOKEN!, {
  metrics: {
    serviceName: 'billing-worker', // the k8s deployment name
    // Fall back explicitly: an unset env var would silently omit the attribute
    // and unlabeled non-prod series would pollute production charts.
    environment: process.env.DEPLOYMENT_ENV ?? 'dev', // 'production' | 'staging' | 'dev'
  },
})
client.metrics.count('invoices.processed', 1, { attributes: { plan: 'pro' } })
```

```python
# Python
client = Posthog(
    os.environ["POSTHOG_PROJECT_TOKEN"],
    metrics={
        "service_name": "billing-worker",  # the k8s deployment name
        "environment": os.environ.get("DEPLOYMENT_ENV", "dev"),
    },
)
client.metrics.count("invoices.processed", 1, attributes={"plan": "pro"})
```

Rules:

- **`service_name` is the k8s deployment name.** Not the repo, not the team, not a nickname. This is the primary filter every chart and alert starts from.
- **`environment` comes from the deployment env var**, so staging noise never pollutes production charts.
- Point at the **PostHog project your team dogfoods in** (project 2 for most internal teams) with that project's token. Metrics are team-scoped like everything else.

## Naming and attributes

- Metric names are **dot-separated, domain first**: `ingestion.lag_seconds`, `billing.invoices.processed`, `hogql.query.duration`. The domain prefix is what makes the name picker usable once fifty services send metrics.
- One name = one type. Don't record `queue.depth` as both a gauge and a counter — the charts blend both series.
- Pick the type by shape: **count** for things that only go up (chart as `rate`/`increase`), **gauge** for levels (chart as `avg`), **histogram** for durations/sizes (chart as `p95`; always set `unit`, usually `ms`).
- Attributes are for **low-cardinality dimensions you'd group by**: `queue`, `route`, `status`, `plan`, `pipeline`. Never user IDs, request IDs, UUIDs, or timestamps — every distinct value is a new series, and the SDK caps at 1000 series per flush window by default (`max_series_per_flush` / `maxSeriesPerFlush`); new series past the cap are dropped with a warning, existing series keep recording.

## What to instrument first

Start with the four that make your service debuggable, then stop:

1. **Throughput** — a count of the unit of work (`<domain>.<thing>.processed`)
2. **Failures** — a count with the same name shape (`<domain>.<thing>.failed`), so `failed / processed` is a one-line formula
3. **Latency** — a histogram of the critical path (`<domain>.<thing>.duration`, unit `ms`)
4. **Backlog** — a gauge of your queue or backlog depth (`<domain>.queue.depth`)

## Verify, then alert

1. Deploy (or run locally against your project) and open **Metrics** in the sidebar — your metric appears in the name picker within a minute of the first flush (SDKs flush every 10s).
2. Filter to your `service.name`, group by your attributes, and confirm the shape is right.
3. **Save as insight**, then add an **alert** on it (Alerts on the insight page) — threshold on the failure rate or backlog gauge is the standard starter. Alerts on metrics insights evaluate every series returned and fire if any breaches.
4. Add the insight to your team's dashboard.

## Gotchas

- Short-lived processes (cron jobs, scripts, tests): call `client.shutdown()` (Node/Python) before exit or the last window is lost.
- Celery/forked workers: create the client after the fork, same rule as event capture. A module-level client created at Django import time in a prefork master (gunicorn `preload_app`) is the classic trap — the Python SDK detects the fork and recovers, but pre-fork samples are dropped rather than duplicated across children.
- The browser SDK attaches no user/session context to metrics by design; don't try to add it via attributes — that's the cardinality explosion the guardrail exists to stop.
- If your service already exposes a Prometheus `/metrics` endpoint that infra scrapes, that keeps working via the collector bridge — the guidance above is for _new, application-level_ instrumentation where you want trace/log correlation and product-context joins.

Questions → #team-apm.
