---
name: monitoring-capture-service
description: >
  Guide for using the Grafana MCP to monitor and diagnose the capture service
  (rust/capture) in production. Use when investigating latency, event loss,
  Kafka backpressure, Redis issues, rate limiting, Envoy proxy issues, or any
  capture health question. Covers prod-us and prod-eu environments.
---

# Monitoring the capture service with Grafana MCP

The capture service (`rust/capture/`) is PostHog's Rust HTTP ingestion endpoint.
It receives events from SDKs, applies quota/rate limits, and produces to Kafka.
Three deployment roles run the same binary with different `CAPTURE_MODE` configs.

This skill teaches how to **discover live metrics** using the Grafana MCP tools
rather than memorizing metric names that change as the code evolves.

## Environment context

The Grafana MCP is connected to a **single Grafana instance** scoped to one environment.
If the user hasn't specified, **ask which environment** they want to investigate:

- **prod-us** — US production (us-east-1)
- **prod-eu** — EU production (eu-central-1)

Most capture app metrics (e.g. `capture_*`, `http_requests_*`, `envoy_cluster_*`) are
environment-specific by virtue of which Grafana you're connected to — they don't carry
an `environment` label. MSK and CloudWatch metrics do carry `environment` labels but
are still scoped to the connected Grafana's AWS account.

Cross-environment comparison requires switching Grafana instances (not possible in one session).

## Observability landscape

Capture spans seven telemetry domains.
Each has a Grafana datasource and a discovery entry point.

| Domain                        | Datasource UID             | Discovery tool                 | Scope filter                              |
| ----------------------------- | -------------------------- | ------------------------------ | ----------------------------------------- |
| App metrics (VictoriaMetrics) | `victoriametrics`          | `list_prometheus_metric_names` | `regex: "capture_.*"`                     |
| App metrics (realtime)        | `victoriametrics-realtime` | same                           | same (lower retention, higher resolution) |
| Logs                          | `P8E80F9AEF21F6940`        | `list_loki_label_names`        | `app=~"capture.*"`                        |
| Profiling                     | `pyroscope`                | `list_pyroscope_profile_types` | `service_name="capture/capture"`          |
| Dashboards                    | n/a                        | `search_dashboards`            | query `"capture"` or `"ingestion"`        |
| CloudWatch (ElastiCache, MSK) | `P034F075C744B399F`        | `query_prometheus`             | `environment="prod-us"`                   |
| CloudWatch Root               | `PAAE47F430CFD1449`        | same                           | root account AWS metrics                  |

## Stable waypoints

These facts change infrequently and are hard to discover dynamically.

### Deployment roles

The `role` label on all `capture_*` and `http_requests_*` metrics distinguishes pipelines:

| Role             | Pipeline           | Notes                       |
| ---------------- | ------------------ | --------------------------- |
| `capture`        | Main events        | Highest volume              |
| `capture-ai`     | AI/LLM events      | OTel ingestion on port 4318 |
| `capture-replay` | Session recordings | `CAPTURE_MODE=recordings`   |

`capture-logs` is a **separate deployment** (not a `role` value on capture metrics).

### Envoy cluster naming

Envoy metrics use `envoy_cluster_name` to identify the upstream backend.
Pattern: `posthog_{deployment}_{port}`.

Capture-related clusters:
`posthog_capture_3000`, `posthog_capture-ai_3000`, `posthog_capture-replay_3000`,
`posthog_capture-replay-canary_3000`, `posthog_capture-logs_4318`, `posthog_capture-logs-canary_4318`.

Scope with: `envoy_cluster_name=~"posthog_capture.*"`.

### Redis instance topology

Capture depends on up to three logical Redis instances,
plus one external instance at the Envoy layer (not in the capture binary).
None emit `capture_redis_*` metrics — Redis health is inferred from capture-side
metrics and CloudWatch ElastiCache metrics.

**1. Primary Redis** (`REDIS_URL` env var)

- ElastiCache: `posthog-solo` (prod-us legacy) or `ingestion-{env}-redis` (prod-eu)
- Backs: billing/quota limits (`CaptureQuotaLimiter`), session replay overflow limiter
- Capture metrics: `capture_billing_limits_loaded_tokens` (by `cache_key`),
  `capture_quota_limit_exceeded` (by `resource`)
- Quota resources: `events`, `exceptions`, `llm_events`, `recordings`, `survey_responses`
- Cache keys: `@posthog/quota-limits/{resource}`, `@posthog/capture-overflow/replay`

**2. Global Rate Limiter Redis** (`GLOBAL_RATE_LIMIT_REDIS_URL`, optional)

- ElastiCache: `capture-globalratelimit-{env}-redis` (prod-us, prod-eu; not dev)
- Backs: per-(token, distinct_id) sliding-window rate limiter
- Falls back to primary Redis when URL is unset
- Optional read replica: `GLOBAL_RATE_LIMIT_REDIS_READER_URL`
- Code defines `global_rate_limiter_*` metrics but they are **not currently emitting**
  in VictoriaMetrics. Best proxy signal: `capture_events_rerouted_overflow{reason="rate_limited"}`
- CloudWatch cluster id: `capture-globalratelimit-prod-redis`

**3. Event Restrictions Redis** (`EVENT_RESTRICTIONS_REDIS_URL`, optional)

- Stores Django-synced ingestion restriction configs
- Falls back to primary Redis when URL is unset
- Capture metrics: `capture_event_restrictions_redis_fetch` (labels: `restriction_type`,
  `result` in success/not_found/error/parse_error),
  `capture_event_restrictions_stale`, `capture_event_restrictions_loaded_count`

**4. Contour Rate Limit Redis** (`ratelimit-{env}-redis`) — NOT in capture binary

- Per-IP DoS protection at the Envoy ingress layer, in front of capture
- Metrics: `ratelimit_service_*` (label: `domain="posthog"`)

### Metric prefixes

Every prefix here can be discovered live with `list_prometheus_metric_names`
using `datasourceUid: "victoriametrics"` and `regex: "<prefix>.*"`.

| Prefix                         | Domain                                  | Scope label                               |
| ------------------------------ | --------------------------------------- | ----------------------------------------- |
| `capture_*`                    | App metrics (68 metrics)                | `role`                                    |
| `http_requests_*`              | HTTP layer (shared)                     | `role=~"capture.*"`                       |
| `capture_kafka_*`              | Kafka producer (17 metrics)             | `role`                                    |
| `capture_billing_*`            | Billing/quota tokens loaded             | `role`, `cache_key`                       |
| `capture_event_restrictions_*` | Event restrictions (6 metrics)          | `role`, `restriction_type`                |
| `capture_ai_otel_*`            | AI/OTel capture (7 metrics)             | `role="capture-ai"`                       |
| `envoy_cluster_*`              | L7 proxy                                | `envoy_cluster_name=~"posthog_capture.*"` |
| `aws_msk_*`                    | MSK broker-side (JMX)                   | `environment="prod-us"`                   |
| `ratelimit_service_*`          | Contour rate limit                      | `domain="posthog"`                        |
| `overflow_redirect_*`          | Node.js ingestion overflow (downstream) | `ingestion_pipeline`                      |
| `kube_*` / `container_*`       | K8s resources                           | `namespace="posthog"`, `pod=~"capture.*"` |

### Kafka topics

Topics capture produces to (discover live via `topic` label on `capture_kafka_produce_avg_batch_size_bytes`):

| Topic                               | Pipeline                                     |
| ----------------------------------- | -------------------------------------------- |
| `ingestion-events-1024`             | Main events                                  |
| `ingestion-events-overflow-128`     | Overflow (rate-limited / high-volume tokens) |
| `ingestion-events-historical-128`   | Historical backfill events                   |
| `ingestion-session_replay-main-256` | Session replay                               |
| `ingestion-heatmaps-128`            | Heatmaps                                     |
| `ingestion-logs`                    | Log ingestion                                |
| `ingestion-general-turbo-1024`      | General turbo                                |
| `ingestion-errortracking-main-128`  | Error tracking                               |
| `client_iwarnings_ingestion`        | Client warnings                              |

### Pyroscope services

| Service name                    | Deployment     |
| ------------------------------- | -------------- |
| `capture/capture`               | Main capture   |
| `capture/capture-ai`            | AI capture     |
| `capture-replay/capture-replay` | Replay capture |
| `capture-logs/capture-logs`     | Logs capture   |

Profile types: `process_cpu:cpu:nanoseconds:cpu:nanoseconds`,
`wall:wall:nanoseconds:wall:nanoseconds`,
`memory:inuse_space:bytes:inuse_space:bytes`,
`memory:inuse_objects:count:inuse_space:bytes`.

### Grafana dashboards

| UID                                    | Title                                                          |
| -------------------------------------- | -------------------------------------------------------------- |
| `capture`                              | Main capture dashboard                                         |
| `ingestion-capture`                    | Capture-specific ingestion metrics                             |
| `ingestion-general`                    | Cross-service ingestion overview                               |
| `ingestion-reliability`                | Error rates and reliability signals                            |
| `ingestion-pipeline-performance`       | End-to-end pipeline latency                                    |
| `b2348f37-f276-498e-b72e-7cc2b5ec1455` | New capture dashboard                                          |
| `contour`                              | Envoy L7 proxy (set `envoy_cluster_name=posthog_capture_3000`) |
| `envoy-contour-debug`                  | Envoy/Contour debugging                                        |
| `qZz6iq9Wx`                            | AWS MSK Kafka Cluster                                          |
| `ingestion-session-recordings`         | Session Replay ingestion                                       |

## Discovery workflows

### Prometheus / VictoriaMetrics

1. `list_prometheus_metric_names` — `datasourceUid: "victoriametrics"`, `regex: "capture_.*"` to enumerate app metrics
2. Pick a metric, then `list_prometheus_label_names` scoped to it — see available dimensions
3. `list_prometheus_label_values` — discover actual values for a label
   (e.g. `labelName: "cause"` on `capture_events_dropped_total`)
4. `query_prometheus` with PromQL — always scope by `role` and set a time range

### Loki (logs)

1. `list_loki_label_names` — `datasourceUid: "P8E80F9AEF21F6940"`
2. `list_loki_label_values` for `app` or `namespace` — find capture containers
3. `query_loki_logs` — e.g. `{app=~"capture.*"} |= "error"`

### Pyroscope (profiling)

1. `list_pyroscope_profile_types` — `data_source_uid: "pyroscope"`
2. `fetch_pyroscope_profile` — `matchers: '{service_name="capture/capture"}'`,
   `profile_type: "process_cpu:cpu:nanoseconds:cpu:nanoseconds"`

### Dashboards

1. `search_dashboards` — query `"capture"` or `"ingestion"`
2. `get_dashboard_by_uid` — use a known UID (e.g. `"capture"`) to get panel details
3. `get_dashboard_panel_queries` — extract PromQL from existing panels

### Redis / ElastiCache

- Capture-side: discover `capture_billing_*`, `capture_event_restrictions_*`,
  `capture_quota_*` metrics in VictoriaMetrics
- Infrastructure: CloudWatch datasource `P034F075C744B399F` for ElastiCache
  (CPU, memory, connections, latency).
  Cluster IDs: `capture-globalratelimit-prod-redis`, `posthog-solo` (prod-us primary)

## Key metric domains

Categories of what to look for. Discover specific metrics live using the prefixes above.

**HTTP layer** — request rate, latency distribution (p50/p99), active connections,
error rates by status code. Metrics: `http_requests_*` scoped by `role`, `capture_active_connections`.

**Event lifecycle** — the funnel from received to ingested to dropped/rerouted.
`capture_events_received_total` -> `capture_events_ingested_total` -> `capture_events_dropped_total`.
The `cause` label on drops has 16 values (discover live).
Rerouting: `capture_events_rerouted_overflow` with `reason` label
(`rate_limited`, `force_limited`, `event_restriction`).

**Kafka producer** — broker connectivity (`capture_kafka_any_brokers_down`,
`capture_kafka_broker_connected`), queue saturation (`_queue_depth` / `_queue_depth_limit`),
produce RTT (`capture_kafka_produce_rtt_latency_us` by `quantile` and `broker`),
delivery errors (`capture_kafka_produce_errors_total`).

**Billing and quota** — `capture_billing_limits_loaded_tokens` by `cache_key`,
`capture_quota_limit_exceeded` by `resource` (events, exceptions, llm_events, recordings, survey_responses).

**Event restrictions** — `capture_event_restrictions_*` for Redis fetch health,
staleness, loaded count, applied restrictions by `restriction_type`
(drop_event, force_overflow, redirect_to_topic, skip_person_processing).

**Envoy proxy** — upstream latency, response codes (2xx/4xx/5xx), connection health,
circuit breakers (`_open` gauges), backend membership (healthy vs total),
timeouts, retries. Always filter: `envoy_cluster_name=~"posthog_capture.*"`.

**Contour rate limit** — `ratelimit_service_*` for per-IP DoS protection.
`ratelimit_service_rate_limit_over_limit` = actively rate-limited IPs.

**MSK broker-side** — `aws_msk_*` JMX metrics. Key signals: throttle time,
network processor idle %, memory pool depletion, request queue size.
Scope: `environment="prod-us"` or `"prod-eu"`.

**K8s resources** — `container_*` and `kube_*` for CPU, memory, restarts, HPA state.
Scope: `namespace="posthog"`, `pod=~"capture.*"`.

## Investigation playbooks

See [references/investigation-playbooks.md](./references/investigation-playbooks.md)
for step-by-step workflows for common questions:
health checks, event loss, latency, Kafka backpressure, rate limiting, Redis, and cross-env comparison.
