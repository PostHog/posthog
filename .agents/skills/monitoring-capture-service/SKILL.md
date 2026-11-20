---
name: monitoring-capture-service
description: >
  Uses the PostHog MCP to monitor and diagnose the capture service
  (rust/capture) in production. Use when investigating latency, event loss,
  Kafka backpressure, Redis issues, rate limiting, Envoy proxy issues, or any
  capture health question. Covers prod-us and prod-eu environments.
---

# Monitoring the capture service with PostHog MCP

The capture service (`rust/capture/`) is PostHog's Rust HTTP ingestion endpoint.
It receives events from SDKs, applies quota/rate limits, and produces to Kafka.
Five deployments run the same binary with different `CAPTURE_MODE` configs, each in its own K8s namespace.

This skill teaches how to **discover live metrics** using the PostHog MCP tools
rather than memorizing metric names that change as the code evolves.

## Environment context

US and EU use separate internal PostHog projects on separate PostHog instances.
If the user hasn't specified, **ask which environment** they want to investigate:

- **prod-us** — US production (us-east-1)
- **prod-eu** — EU production (eu-central-1)

Use the PostHog MCP connection for the region's internal project.
US metrics carry `environment="prod-us"`.
For EU, run the same tools through a separate connection to the EU PostHog instance.
Discover labels and filter or check `environment` where it exists.
An environment filter does not switch projects or instances.
If a region's connection is unavailable, report that region as not checked.

## Observability landscape

Capture spans app metrics, infrastructure metrics, logs, profiles, and dashboards.
Use PostHog for metrics and logs. Confirm each metric exists in the selected region before querying.

| Domain                                         | Discovery or access                                             |
| ---------------------------------------------- | --------------------------------------------------------------- |
| App metrics                                    | `posthog:metric-names-list`                                     |
| Logs                                           | `posthog:logs-attribute-values-list`, then `posthog:query-logs` |
| Infrastructure metrics (ElastiCache, MSK, K8s) | `posthog:metric-names-list`, then `posthog:query-metrics`       |
| Profiling                                      | Existing Pyroscope access                                       |
| Dashboards                                     | Existing Grafana access                                         |

**Fallback:** People on managed devices with an existing Grafana MCP connection can use it.
It supports metrics, logs, profiles, and dashboards.
See `tools/infra-scripts/mcp/README.md` for its setup.

## Stable waypoints

These facts change infrequently and are hard to discover dynamically.

### Deployment roles

Each capture variant runs as a **separate K8s deployment in its own namespace**.
The primary scope labels are `namespace` and `container` (not `role` — that label
contains pod names and is not useful for filtering).

| Deployment          | Namespace           | `capture_mode` | Pipeline           | Notes                                         |
| ------------------- | ------------------- | -------------- | ------------------ | --------------------------------------------- |
| `capture-analytics` | `capture-analytics` | `events`       | Main events        | Highest volume; routes `/e`, `/i/v0/e`, etc.  |
| `capture-ai`        | `capture-ai`        | `events`       | AI/LLM events      | Routes `/i/v0/ai`; OTel on port 4318          |
| `capture-replay`    | `capture-replay`    | `recordings`   | Session recordings | Routes `/s/`; `CAPTURE_MODE=recordings`       |
| `capture-mirrored`  | `capture-mirrored`  | `events`       | Mirror/canary      | Not always running; same metrics as analytics |
| `capture-logs`      | `capture-logs`      | —              | Log ingestion      | OTel logs on port 4318                        |

All variants share the same Rust binary (`ghcr.io/posthog/posthog/capture`).

Scope capture metrics with `namespace=~"capture-.*"` or `container=~"capture-.*"`.
For a single pipeline, scope by `namespace` (e.g., `namespace="capture-analytics"`).

### Envoy cluster naming

Envoy metrics use `envoy_cluster_name` to identify the upstream backend.
Pattern: `{namespace}_{service}_{port}`, the same in prod-us and prod-eu.

Capture-related clusters:
`capture-analytics_capture-analytics_3000`, `capture-ai_capture-ai_3000`, `capture-replay_capture-replay_3000`,
`capture-logs_capture-logs_4318`, `capture-logs_capture-logs-canary_4318`, `capture-apm-metrics_capture-apm-metrics_4318`.

capture-replay's KEDA autoscaling reads `capture-replay_capture-replay_3000`.

Scope with: `envoy_cluster_name=~"capture-.*"`.

### Redis instance topology

Capture depends on up to three logical Redis instances,
plus one external instance at the Envoy layer (not in the capture binary).
None emit `capture_redis_*` metrics — Redis health is inferred from capture-side
metrics and CloudWatch ElastiCache metrics.

**1. Primary Redis** (`REDIS_URL` env var)

- ElastiCache: `posthog-solo` (prod-us) or `posthog-prod-redis-encripted` (prod-eu; sic — typo in actual cluster name)
- Both envs use a **read-only** endpoint for the token cache (`REDIS_READER_URL`)
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
- Toggle: `GLOBAL_RATE_LIMIT_ENABLED` (may be off in some envs during rollout)
- Metrics: `global_rate_limiter_*` (direct), `capture_events_rerouted_overflow{reason="rate_limited"}` (proxy signal)
- `global_rate_limiter_window_seconds{scope}` publishes each process's window. capture-analytics and capture-ai share the AI byte budget, so if they disagree on this gauge the shared budget has split
- CloudWatch cluster id: `capture-globalratelimit-prod-redis`

**3. Event Restrictions Redis** (`EVENT_RESTRICTIONS_REDIS_URL`)

- ElastiCache: `ingestion-prod-redis` (separate writable cluster in both envs)
- Stores Django-synced ingestion restriction configs
- Falls back to primary Redis when URL is unset
- Capture metrics: `capture_event_restrictions_redis_fetch` (labels: `restriction_type`,
  `result` in success/not_found/error/parse_error),
  `capture_event_restrictions_stale`, `capture_event_restrictions_loaded_count`

**4. Contour Rate Limit Redis** (`ratelimit-{env}-redis`) — NOT in capture binary

- Per-IP DoS protection at the Envoy ingress layer, in front of capture
- Metrics: `ratelimit_service_*` (label: `domain="posthog"`)

### Metric prefixes

Discover each prefix with `posthog:metric-names-list` using `value: "<prefix>"`.
The default match is a substring. Use `match: "regex"` for a regular expression.

| Prefix                         | Domain                                  | Scope label                                    |
| ------------------------------ | --------------------------------------- | ---------------------------------------------- |
| `capture_*`                    | App metrics (~80 metrics)               | `namespace`, `container`                       |
| `http_requests_*`              | HTTP layer (shared)                     | `namespace=~"capture-.*"`                      |
| `capture_kafka_*`              | Kafka producer (17 metrics)             | `namespace`, `container`                       |
| `capture_billing_*`            | Billing/quota tokens loaded             | `namespace`, `cache_key`                       |
| `capture_event_restrictions_*` | Event restrictions (6 metrics)          | `namespace`, `restriction_type`                |
| `capture_ai_otel_*`            | AI/OTel capture (12 metrics)            | `namespace="capture-ai"`                       |
| `envoy_cluster_*`              | L7 proxy                                | `envoy_cluster_name=~"capture-.*"`             |
| `aws_msk_*`                    | MSK broker-side (JMX)                   | `environment="prod-us"` or `"prod-eu"`         |
| `ratelimit_service_*`          | Contour rate limit                      | `domain="posthog"`                             |
| `overflow_redirect_*`          | Node.js ingestion overflow (downstream) | `ingestion_pipeline`                           |
| `kube_*` / `container_*`       | K8s resources                           | `namespace=~"capture-.*"`, `pod=~"capture-.*"` |

### Kafka topics

Topics capture produces to (discover live via `topic` label on `capture_kafka_produce_avg_batch_size_bytes`).
Partition counts are encoded in topic names and **differ by env** (EU generally has fewer partitions).

Capture writes to **two different Kafka backing systems** depending on the pipeline:

- **MSK ingestion cluster** — analytics events (main, overflow, historical, turbo), heatmaps, error tracking, client warnings
- **WarpStream** — session replay (`warpstream-replay-v2` VC), logs (`warpstream-logs` VC), traces (`warpstream-traces` VC)

| Topic (prod-us / prod-eu)                                  | Backing    | Pipeline                                     |
| ---------------------------------------------------------- | ---------- | -------------------------------------------- |
| `ingestion-analytics-main-1024` / `-512`                   | MSK        | Main events                                  |
| `ingestion-analytics-overflow-128`                         | MSK        | Overflow (rate-limited / high-volume tokens) |
| `ingestion-analytics-historical-128`                       | MSK        | Historical backfill events                   |
| `ingestion-analytics-turbo-1024`                           | MSK        | General turbo (prod-us only)                 |
| `ingestion-heatmaps-main-128`                              | MSK        | Heatmaps                                     |
| `ingestion-errortracking-main-128`                         | MSK        | Error tracking                               |
| `ingestion-errortracking-overflow-32`                      | MSK        | Error tracking overflow                      |
| `ingestion-clientwarnings-main-16` / `-32`                 | MSK        | Client warnings                              |
| `ingestion-sessionreplay-main-512` / `-256`                | WarpStream | Session replay                               |
| `ingestion-sessionreplay-overflow-64` / `-32`              | WarpStream | Session replay overflow                      |
| `ingestion-logs`                                           | WarpStream | Log ingestion                                |
| `ingestion-traces`                                         | WarpStream | Traces ingestion                             |
| `ingestion-analytics-main-dlq` (+ per-pipeline DLQ topics) | MSK        | Dead letter queues                           |

### Pyroscope services

| Service name                          | Deployment                   |
| ------------------------------------- | ---------------------------- |
| `capture-analytics/capture-analytics` | Main capture                 |
| `capture-ai/capture-ai`               | AI capture                   |
| `capture-replay/capture-replay`       | Replay capture               |
| `capture-mirrored/capture-mirrored`   | Mirror/canary (when running) |
| `capture-logs/capture-logs`           | Logs capture                 |

Profile types: `process_cpu:cpu:nanoseconds:cpu:nanoseconds`,
`wall:wall:nanoseconds:wall:nanoseconds`,
`memory:inuse_space:bytes:inuse_space:bytes`,
`memory:inuse_objects:count:inuse_space:bytes`.

### Grafana dashboards

| UID                       | Title                      | Use for                                                                            |
| ------------------------- | -------------------------- | ---------------------------------------------------------------------------------- |
| `capture`                 | Capture                    | Overview across capture deployments — start here                                   |
| `capture-v1-details`      | V1 Details                 | Per-panel detail for the v1 pipeline (`/i/v1/analytics/events`)                    |
| `ddfkdj56ds11xce`         | Legacy Details             | Per-panel detail for the legacy v0 pipeline (`/e/`, `/batch/`, `/i/v0/e/`)         |
| `ingestion-health`        | Ingestion - Health         | Cross-service ingestion health                                                     |
| `ingestion-analytics`     | Ingestion - Analytics      | Downstream analytics pipeline, per lane                                            |
| `ingestion-pipelines`     | Ingestion - Pipelines      | End-to-end pipeline throughput and lag                                             |
| `ingestion-reliability`   | Ingestion - Reliability    | Ingested-event trends, processing-lag SLOs, pod restarts                           |
| `ingestion-sessionreplay` | Ingestion - Session Replay | Session replay ingestion                                                           |
| `contour`                 | Contour Ingress            | Envoy L7 proxy (set `envoy_cluster_name=capture-analytics_capture-analytics_3000`) |
| `AWSRedis`                | AWS ElastiCache Redis      | Per-cluster CloudWatch Redis metrics (filter `cacheclusterId`)                     |

The two details boards live under `Capture/Ingestion/` and cross-link each other
plus the overview. Sections for machinery shared by both pipelines (Global Rate
Limiter, Event restrictions, Hyper server, Contour, billing/quota) appear on
**both** details boards, so use whichever one you are already on.

One board you may find in Grafana but should not rely on:
`capture-3000-envoy-codes` is a personal, US-only Envoy investigation board (not
synced to EU).

## Discovery workflows

### Metrics

1. Call `posthog:metric-names-list` with `value: "capture_"` to discover exact names and metric types.
2. Call `posthog:metric-attributes-list` with `metricName` to discover labels.
3. Call `posthog:metric-attribute-values-list` to discover values, such as `cause` on `capture_events_dropped_total`.
4. Call `posthog:query-metrics` with the existing PromQL in `query.promql` as written.
   Scope new expressions by `namespace` or `container`. Check `environment` where it exists.

Set `query.dropEmptySeries: false` for health checks so zero-valued series keep their labels.
This preserves failing cache keys when quota loading stays at zero.
All query parameters go inside `query`. For a range summary:

```json
{
  "query": {
    "promql": "capture_kafka_any_brokers_down",
    "dateFrom": "-1h",
    "output": "summary",
    "dropEmptySeries": false
  }
}
```

Use `query.instant: true` for current values. Omit `dateFrom` and `dateTo` for instant queries.
For a curve, keep the range and omit `output`. Share the returned `_posthogUrl` with the user.
Keep existing PromQL expressions unchanged. Do not translate them into builder fields.
If PromQL is unavailable or a metric is missing, report the limit before using the fallback.

### Logs

1. Discover services with `posthog:logs-attribute-values-list` using `key: "service.name"` and `attribute_type: "resource"`.
2. Select the capture service. Discover resource labels with `posthog:logs-attributes-list` using `attribute_type: "resource"` when needed.
3. Follow the tool's count and time-window guidance before calling `posthog:query-logs`.
   Set `query.serviceNames` to the discovered services and always pass `query.dateRange`.
   For errors, use `query.severityLevels: ["error", "fatal"]`. Use `query.searchTerm` for message text.
   If severity filters return nothing unexpectedly, discover stored severity values before concluding there are no errors.

Example after confirming the service name:

```json
{
  "query": {
    "serviceNames": ["capture-analytics"],
    "dateRange": { "date_from": "-1h" },
    "severityLevels": ["error", "fatal"]
  }
}
```

### Pyroscope (profiling)

Use existing Pyroscope access for profiles. See the service names and profile types above.
Profiling through Grafana requires the fallback connection.

### Dashboards

Use existing Grafana access to inspect the dashboards listed above.
Send a panel's PromQL to `posthog:query-metrics` in `query.promql` as written.
Dashboard access through MCP requires the fallback connection.

### Redis / ElastiCache

- Capture-side: discover `capture_billing_*`, `capture_event_restrictions_*`,
  `capture_quota_*` metrics with `posthog:metric-names-list`
- Infrastructure: ingested CloudWatch metrics in PostHog for ElastiCache
  (CPU, memory, connections, latency).
  Cluster IDs: `capture-globalratelimit-prod-redis`, `posthog-solo` (prod-us primary)

## Key metric domains

Categories of what to look for. Discover specific metrics live using the prefixes above.

**HTTP layer** — request rate, latency distribution (p50/p99), active connections,
error rates by status code. Metrics: `http_requests_*` scoped by `namespace`, `capture_active_connections`.

**Event lifecycle** — the funnel from received to ingested to dropped/rerouted.
`capture_events_received_total` -> `capture_events_ingested_total` -> `capture_events_dropped_total`.
The `cause` label on drops has 20+ values (discover live). Key additions since the golden-chart
migration: `event_restriction_drop`, `event_too_big`, `otel_quota_drop`, `oversize_event`,
`ai_opt_in`, `gathering`, `invalid_session`, `no_session_id`, `no_snapshot`.
Rerouting: `capture_events_rerouted_overflow` with `reason` label
(`rate_limited`, `force_limited`, `event_restriction`).
Also: `capture_events_rerouted_custom_topic` for topic-redirect restrictions.

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
timeouts, retries. Always filter: `envoy_cluster_name=~"capture-.*"`.
For capture-replay, also check `proxy-as-a-service_capture-replay_3000`.

**Contour rate limit** — `ratelimit_service_*` for per-IP DoS protection.
`ratelimit_service_rate_limit_over_limit` = actively rate-limited IPs.

**MSK broker-side** — `aws_msk_*` JMX metrics for capture-analytics, capture-ai, and other MSK-backed topics.
Key signals: throttle time, network processor idle %, memory pool depletion, request queue size.
Both envs have a **dedicated ingestion MSK** cluster separate from the events cluster
(prod-us: c21; prod-eu: `posthog-prod-eu-ingestion-2026-05-04`).

**WarpStream** — `warpstream_agent_*` metrics for capture-replay, capture-logs, and traces.
These pipelines produce to in-cluster WarpStream agents, not MSK.
Key signals: `warpstream_agent_control_plane_operation_counter` (by `operation`),
`warpstream_agent_file_cache_client_fetch_local_or_remote_counter` (cache hit/miss ratio).
Dashboards: `warpstream` (Agent Overview), `dbfj5c31spa1ogf` (MSK vs WarpStream — Active Produce Topics).
US-only personal dashboards (not synced to EU): `ws-coarse-lag-explore` (Coarse Lag), `8e93b023-…` (CH Consumer Lag).
Per-VC KMinion instances: `kminion-warpstream-replay`, `kminion-warpstream-logs`, `kminion-warpstream-traces`.

**K8s resources** — `container_*` and `kube_*` for CPU, memory, restarts, HPA state.
Scope: `namespace=~"capture-.*"`, `pod=~"capture-.*"`.

## Investigation playbooks

See [references/investigation-playbooks.md](./references/investigation-playbooks.md)
for step-by-step workflows for common questions:
health checks, event loss, latency, Kafka backpressure, rate limiting, Redis, and cross-env comparison.
