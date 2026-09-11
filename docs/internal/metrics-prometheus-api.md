# Metrics Prometheus read API (Grafana datasource)

A thin, authorized reverse proxy in front of [Snuffle](https://github.com/PostHog/snuffle) that lets a Grafana Prometheus datasource read PostHog Metrics. PostHog owns authentication, scope, feature flags, throttling, and team binding; Snuffle is the PromQL engine over ClickHouse and stays user-agnostic.

```
Grafana --(Authorization: Bearer phx_…)--> Django /api/projects/<id>/metrics/prometheus/api/v1/*
        --(X-Team-ID: <id>, service Basic creds)--> Snuffle --> ClickHouse
```

The customer-facing gap this closes: a Metrics alpha customer needs their existing Grafana dashboards to read metrics from PostHog. Today they dual-write (`remote_write` to their Prometheus and to PostHog). This endpoint is the path off that bridge. Snuffle-side support (job/instance aliases, `/api/v1/status/buildinfo`, header-only tenant mode) is in [PostHog/snuffle](https://github.com/PostHog/snuffle).

## Endpoint

`GET|POST /api/projects/<team_id>/metrics/prometheus/api/v1/<path>` — Grafana's datasource URL is the `…/metrics/prometheus` base; it appends `/api/v1/…`.

Auth: a personal API key with the `metrics:read` scope, sent as `Authorization: Bearer phx_…` (Grafana datasource → custom HTTP header). Both feature flags must be on: `metrics` (alpha) and `metrics-prometheus-api`.

## What is proxied

Only read paths Grafana uses; anything else returns a Prometheus `{"status":"error","errorType":"not_found"}` 404.

| Path | Why |
| --- | --- |
| `query`, `query_range` | panels, instant, Save & Test |
| `labels`, `label/<name>/values`, `series`, `metadata` | metric browser, autocomplete, template variables |
| `status/buildinfo` | Grafana datasource Save & Test |
| `query_exemplars`, `rules`, `alerts` | stubs / empty in posthog layout |

Blocked: `write` (would bypass the Kafka ingest and series fingerprinting), `read` (remote read — a bulk-export surface with no cost cap, and Grafana does not need it), `admin/*`, `status/*` other than `buildinfo`, `targets`, `format_query`.

## Tenant and credential handling

- The tenant is bound from the URL team and sent to Snuffle as `X-Team-ID: <team.pk>`. A client-supplied `X-Team-ID` header or `team_id`/`tenant` query param is dropped/overridden — Grafana cannot pick a tenant.
- The upstream call uses `internal_httpx_client` (no env-proxy) with `METRICS_PROMQL_INTERNAL_BASIC_AUTH` as the service ClickHouse credentials, so ClickHouse grants cap the blast radius.
- Client `Authorization`, `Cookie`, `Accept-Encoding`, hop-by-hop, and `X-Grafana-*` headers are not forwarded.
- Upstream status (400/422/503) and JSON body pass through verbatim; Grafana renders `error` from the envelope. Connection failure or an unconfigured URL returns `{"status":"error","errorType":"unavailable"}` 503 without leaking the upstream URL.

## Settings

| Env var | Default | Purpose |
| --- | --- | --- |
| `METRICS_PROMQL_INTERNAL_URL` | `http://localhost:9091` in DEBUG, else empty | Snuffle base URL |
| `METRICS_PROMQL_INTERNAL_BASIC_AUTH` | empty | `user:password` for Snuffle's ClickHouse |
| `METRICS_PROMQL_TIMEOUT_SECONDS` | `60` | Upstream timeout; keep ≥ Snuffle `PROMQL_QUERY_TIMEOUT_SECONDS` |

Set `METRICS_PROMQL_TIMEOUT_SECONDS` at or above Snuffle's query timeout so Snuffle's own timeout envelope reaches Grafana instead of a 503.

## Snuffle deployment (infra, out of this repo)

`CH_SCHEMA_LAYOUT=posthog`, `CH_SAMPLES_TABLE=metrics` (Distributed), `CH_ATTRIBUTE_TABLE=metric_attributes`, `SNUFFLE_TEAM_SOURCE=header`, `SNUFFLE_SELF_SCRAPE_ENABLED=false` (read-only CH user), `SNUFFLE_ALLOW_UNAUTHENTICATED=false`, and `CH_QUERY_SETTINGS=max_bytes_to_read=…,read_overflow_mode=throw,max_execution_time=…`. Dedicated read-only ClickHouse user with SELECT on the four metrics tables and a matching settings profile. Network policy so only Django pods reach Snuffle.

## Local end-to-end

1. `hogli up -d && hogli wait`; seed metrics (`products/metrics/backend/tests/_seeder.py` `seed_metric`, or remote-write to `:8010/i/v1/prometheus/write`).
2. Run Snuffle in posthog mode against the local `posthog` ClickHouse with `SNUFFLE_TEAM_SOURCE=header`.
3. `METRICS_PROMQL_INTERNAL_URL=http://localhost:9091`; enable `metrics` + `metrics-prometheus-api`; create a PAK with `metrics:read`.
4. `curl -H "Authorization: Bearer phx_…" "http://localhost:8010/api/projects/<id>/metrics/prometheus/api/v1/query_range" --data-urlencode 'query=sum by (job) (rate(http_requests_total[5m]))' --data-urlencode start=… --data-urlencode end=… --data-urlencode step=60`.
5. Grafana in Docker pointed at the same base URL; confirm Save & Test and a panel render.

## Success metric

`metrics prometheus api called` events (endpoint, method, upstream_status, duration_ms, client) per team per day; Snuffle `snuffle_promql_query_duration_seconds` and `snuffle_clickhouse_read_bytes_total`.
