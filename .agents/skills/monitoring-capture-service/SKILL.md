---
name: monitoring-capture-service
description: >
  Monitor and diagnose the capture service (rust/capture) in prod-us and prod-eu with
  verified metrics, Loki logs, dashboards and alerts. Use when investigating capture
  latency, errors, event loss, legacy (v0) versus v1 endpoint behavior, billing quota
  drops, the global rate limiter, event restrictions, Redis health, Kafka or WarpStream
  produce problems, Envoy or edge rate limiting, or any capture health question.
---

# Monitoring the capture service

The capture service (`rust/capture/`) is PostHog's Rust HTTP intake.
It authenticates, validates and limits events, then produces them to Kafka or WarpStream.
One binary runs as four deployments, picked by `CAPTURE_MODE`.

Every name, label and value below was read from production (prod-us and prod-eu) and the code on `master`.
Counters only get a series after their first increment, so a missing series can mean "never happened" rather than "broken".
Confirm a name with the discovery tools before you conclude anything from an empty result.

## Tools and datasources

Two tool sets reach the same data. Use either, and say which one you used.

| Tool set                                 | Metrics                                                                                                                 | Logs                                                                    | Notes                                                                                                                                                                       |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PostHog MCP (US project 2)               | `metric-names-list`, `metric-attributes-list`, `metric-attribute-values-list`, then `query-metrics` with `query.promql` | `logs-attribute-values-list`, `logs-attributes-list`, then `query-logs` | Log `service.name` equals the namespace, for example `capture-analytics`. `metric-names-list` can report a counter as `gauge`; use `rate` or `increase` on counters anyway. |
| Grafana MCP (`grafana-us`, `grafana-eu`) | Prometheus datasource UID `victoriametrics`                                                                             | Loki datasource UID `P44D702D3E93867EC`                                 | Same UIDs in both regions. Profiles: Pyroscope datasource `pyroscope` (US). Dashboards: `search_dashboards`, `get_dashboard_summary`, `get_dashboard_panel_queries`.        |

Ask which region to check when the user does not say. Query each region with its own tools; an `environment` label (`prod-us`, `prod-eu`) does not switch instances.
Health checks: keep zero-valued series (`query.dropEmptySeries: false` in PostHog) so a failing label still shows.

## Deployments

| Namespace           | Deployments                          | `capture_mode` label | Serves (paths seen in `http_requests_total`)                                                   | Produces to                            |
| ------------------- | ------------------------------------ | -------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------- |
| `capture-analytics` | `capture-analytics-1a`, `-1b`, `-1c` | `events`             | Legacy `/e`, `/batch`, `/capture`, `/i/v0/e`, `/track`, `/engage`; v1 `/i/v1/analytics/events` | MSK ingestion cluster                  |
| `capture-ai`        | `capture-ai-1a`, `-1b`, `-1c`        | `ai`                 | Legacy `/i/v0/ai`, `/i/v0/ai/batch`, `/i/v0/ai/otel`; v1 `/i/v1/ai/events`                     | WarpStream (ingestion virtual cluster) |
| `capture-replay`    | `capture-replay-1a`, `-1b`, `-1c`    | `recordings`         | `/s`                                                                                           | WarpStream (replay virtual cluster)    |
| `capture-import`    | `capture-import`                     | `import`             | Same paths as analytics; only historical backfills are kept                                    | MSK ingestion cluster                  |

- Route selection is in `rust/capture/src/router.rs` (`match capture_mode`, `serves_v1_analytics`, `serves_v1_ai_events`).
- Paths may appear with or without a trailing slash; match both, for example `path=~"/batch/?"`.
- `capture-mirrored` exists as a deployment with 0 replicas in both regions and serves nothing.
- `capture-logs` and `capture-apm-metrics` share the `capture-` prefix but are other binaries (`rust/capture-logs`, `rust/capture-apm-metrics`, metric prefixes `capture_logs_*` and `capture_metrics_*`). This skill does not cover them; exclude them with `namespace=~"capture-(analytics|ai|replay|import)"`.

## Labels on capture metrics

- Every capture app metric carries `namespace`, `role` (the namespace name), `capture_mode`, `pod`, `topology_kubernetes_io_zone`, `environment` and `cluster_name`.
- App metrics have **no `container` label**. `container` exists only on cAdvisor (`container_*`) metrics and on Loki streams.
- Gauges are per pod. Aggregate them with `max`, `min` or `avg`, never `sum`, unless the gauge is a count you mean to add up.
- Summaries (metrics with a `quantile` label, such as `capture_v1_processing_duration_seconds`) cannot be re-aggregated across pods: use `max by (quantile)` for the worst pod.

## Legacy (v0) versus v1: how to scope

| Question             | Legacy (v0)                                                                                 | v1                                                                                                                            |
| -------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Requests and latency | `http_requests_total`, `http_requests_duration_seconds_bucket` with `path!~"/i/v1/.*"`      | `capture_v1_response_time_seconds_bucket{path=~"/i/v1/.*"}` (or `http_requests_total{path=~"/i/v1/.*"}`, which counts v1 too) |
| Events in            | `capture_events_received_total` (legacy only)                                               | `capture_v1_parsed_events{result}` and `capture_v1_event_batch_size`                                                          |
| Events out to Kafka  | `capture_events_ingested_total` (shared: one per acked message, both pipelines)             | same metric; no per-pipeline split                                                                                            |
| Drops                | `capture_events_dropped_total{cause}`                                                       | `capture_v1_events_dropped{reason,stage}`, per-request `capture_v1_batch_outcomes{outcome}`                                   |
| Request errors       | `capture_error_by_stage_and_type{stage,error}`                                              | `capture_v1_analytics_error{error,status_code,path}`                                                                          |
| Billing quota        | `capture_quota_limit_exceeded{resource}`                                                    | `capture_v1_events_quota_limited{resource}`, whole-request `capture_v1_analytics_error{error="billing_limit_exceeded"}` (402) |
| Restrictions         | `capture_event_restrictions_applied{pipeline,restriction_type}` (process-wide, counts both) | `capture_v1_events_restricted{action}`                                                                                        |
| Global rate limiter  | `capture_events_rate_limited_token_distinctid{reason}`                                      | `capture_v1_rate_limiter{limiter,outcome}`                                                                                    |
| Ingestion warnings   | `ingestion_warnings_total{path="legacy_analytics"}` (also `replay`, `ai_otel`)              | `ingestion_warnings_total{path="v1_analytics"}`                                                                               |
| Logs                 | `target` not under `capture::v1::`                                                          | `target=~"capture::v1::.*"`, field `path`                                                                                     |

- The v1 quota shim does not touch the legacy quota or drop counters (`rust/capture/src/v1/quota_limiter_shim.rs`), so legacy and v1 numbers never double count.
- The Envoy cluster is shared by v0 and v1 and cannot be split by route. Use app metrics for per-pipeline views (the same reasoning is written in charts `alerts/specs/capture-analytics.yaml`).

## Metric catalog

Names with their facet labels. Paths are where the code emits them (`rust/` prefix omitted).

**HTTP and server** (`capture/src/metrics_middleware.rs`, `capture/src/server.rs`, `capture/src/extractors.rs`)

- `http_requests_total`, `http_requests_duration_seconds_bucket` — `method`, `path`, `status`. Covers legacy and v1.
- `capture_active_connections` — in-flight connections per pod.
- `capture_hyper_accepted_connections{stage}`, `capture_hyper_accept_error{stage,err_type}`, and `capture_hyper_header_read_timeout{stage}` (absent until it fires).
- `capture_rejected_body_drain_total{path,outcome,reason}` — bodies drained after a rejection.

**Legacy event funnel** (`capture/src/payload/`, `capture/src/prometheus.rs`, `capture/src/sinks/producer.rs`)

- `capture_events_received_total` → `capture_events_ingested_total`; drops in `capture_events_dropped_total{cause}`.
- Live `cause` values: `events_over_quota`, `exceptions_over_quota`, `recordings_over_quota`, `llm_events_over_quota`, `survey_responses_over_quota`, `token_dropper`, `no_distinct_id`, `no_event_name`, `event_restriction_drop`, `otel_quota_drop`, `oversize_event`, `ai_byte_rate_limited`, `ai_event_too_big`, `kafka_message_size`, `event_too_big`, `invalid_session`, `no_session_id`, `no_snapshot`, `invalid_cookieless`.
- `capture_error_by_stage_and_type{stage,error}` — stages `parsing`, `processing`, and on capture-ai `otel_auth`, `otel_body_read`, `otel_parsing`, `otel_validation`.
- `capture_events_rerouted_overflow{reason}` — `event_restriction`, `rate_limited`, `force_limited`; `capture_events_rerouted_custom_topic{reason}`.
- Payload: `capture_raw_payload_size`, `capture_full_payload_size{oversize}`, `capture_payload_size_exceeded{kind}`, `capture_gzip_decompression_ratio`, `capture_lz64_decompression_ratio`, `capture_form_base64_decoded_total{outcome}`, `capture_event_batch_size`.
- Timestamps: `capture_client_clock_skew_seconds`, `capture_edge_timestamp_rejected_total{edge,reason}`, `capture_timestamp_path_total{ts_path}`.

**v1 pipeline** (`capture/src/v1/`)

- `capture_v1_response_time_seconds_bucket{path,status}`, `capture_v1_processing_duration_seconds{path,quantile}`.
- `capture_v1_batch_outcomes{path,outcome}` — `all_ok`, `partial_failure`, `all_drop`, `all_retry`.
- `capture_v1_analytics_error{error,status_code,path}` — `path="unknown"` when the request failed before routing data was read, for example `missing_required_headers` (400) or `missing_authorization` (401).
- `capture_v1_analytics_warning{path,reason}` — for example `sdk_info_unparseable`, `duplicate_event_uuid`.
- `capture_v1_parsed_events{result}`, `capture_v1_events_dropped{reason,stage}`, `capture_v1_event_adjustments_applied{reason}`, `capture_v1_events_rerouted_historical{reason}` (capture-import: `batch_flag`).
- `capture_v1_rate_limiter{limiter,outcome}` — `limiter="token_distinct_id"`, outcomes `allowed`, `limited`, `already_disabled`.
- `capture_v1_events_restricted{action}` — `redirect_to_topic`, `force_overflow`, `skip_person_processing`, `redirect_to_dlq`.
- Size and timing: `capture_v1_payload_size_bytes{stage,encoding}`, `capture_v1_event_batch_size`, `capture_v1_clock_skew_seconds`, `capture_v1_serialize_duration_seconds{batch_size}`, `capture_v1_body_read_timeout_total{path}`.
- Loss counters that stay absent until they fire: `capture_v1_serialize_failed_total`, `capture_v1_serialize_panic_total`, `capture_v1_decompression_errors_total{encoding}`.
- `capture_v1_gateway_provenance{reason}` on capture-ai: live `verified`; the code also emits `forged`, `stale`, `stripped`, `dropped_unparseable` (`capture/src/v1/analytics/process.rs`). The OTel path has `capture_ai_otel_gateway_provenance{reason}` (live `unsigned`).
- Django's v1 client reports `capture_v1_internal_*` (submitted, results, failures) from the Django and Temporal worker namespaces, not from capture.

**Billing quota** (`common/limiters/src/redis.rs`, `capture/src/quota_limiters.rs`, `capture/src/v1/quota_limiter_shim.rs`)

- `capture_billing_limits_loaded_tokens{cache_key}` — per pod, use `max by (namespace, cache_key)`. Keys `@posthog/quota-limits/{events,exceptions,llm_events,recordings,survey_responses}` and `@posthog/capture-overflow/replay` (replay overflow set; 0 is normal).
- A failed refresh logs `Failed to update cache from Redis` (`target="limiters::redis"`) and keeps serving the last loaded set.

**Event restrictions** (`capture/src/event_restrictions/`)

- `capture_event_restrictions_applied{pipeline,restriction_type}`, `capture_event_restrictions_redis_fetch{restriction_type,result}` (`success`, `not_found`, `error`, `parse_error`).
- Gauges per `pipeline`: `capture_event_restrictions_stale`, `capture_event_restrictions_loaded_count`, `capture_event_restrictions_tokens_count`, `capture_event_restrictions_last_refresh_timestamp`.
- Pipelines: `analytics`, `ai`, `errortracking`, `heatmaps`, `clientwarnings`, `session_recordings`. A stale config fails open (applies no restrictions) after `EVENT_RESTRICTIONS_FAIL_OPEN_AFTER_SECS`, default 300.

**Global rate limiter (GRL)** (`common/limiters/src/global_rate_limiter.rs`, scopes built in `capture/src/global_rate_limiter.rs`)

- Scope label `<capture_mode>_<limiter>`: `events_tok_distid` (per token and distinct id, capture-analytics), `events_ai_bytes` (AI bytes on capture-analytics), `ai_ai_bytes` (capture-ai).
- Decisions: `global_rate_limiter_eval_counts_total{scope,result}` (`allowed`, `limited`), `global_rate_limiter_cache_counts_total{scope,result}`.
- Health: `global_rate_limiter_error_total{scope,step,cause,redis_idx}`, `global_rate_limiter_read_failing_seconds{scope,redis_idx}`, `global_rate_limiter_pipeline_ms`, `global_rate_limiter_tick_ms`, `global_rate_limiter_update_channel_depth`, `global_rate_limiter_pending_sync_size`, `global_rate_limiter_sync_staleness_ms`, `global_rate_limiter_sync_tier_gauge{tier}`, `global_rate_limiter_eviction_total{cause}`, `global_rate_limiter_cache_size`, `global_rate_limiter_window_seconds`, `global_rate_limiter_custom_thresholds_fetch_total{result}`.
- `redis_idx` is the shard: `0` is `capture-globalratelimit`, `1` is `capture-globalratelimit-2`. Only capture-analytics uses two shards.
- Prod settings (charts `apps/capture-analytics/values.prod-*.yaml`): enabled, not dry run, window 120 s for `tok_distid` (180 s for AI bytes), threshold 10000.
- App-side effects: `capture_events_rate_limited_token_distinctid{reason}` and `capture_global_rate_limiter_already_disabled{over_budget}` (legacy), `capture_v1_rate_limiter` (v1).

**Overflow and partition limiter**: `partition_limits_key_count{lane}` (`common/limiters/src/overflow.rs`), plus the reroute counters above.

**AI lane** (`capture/src/otel/`, `capture/src/ai_endpoint.rs`): `capture_ai_otel_requests_total{format}`, `capture_ai_otel_requests_success`, `capture_ai_otel_spans_accepted`, `capture_ai_otel_spans_filtered`, `capture_ai_otel_events_ingested`, `capture_ai_otel_body_size_bytes`. AI byte limits show as GRL `*_ai_bytes` scopes and the `ai_byte_rate_limited` drop cause.

**Kafka producer, shared by every pipeline** (`capture/src/sinks/kafka.rs`, `capture/src/sinks/producer.rs`)

- `capture_kafka_produce_ack_duration_ms{topic,outcome}` (`ok`, `dropped`), `capture_kafka_produce_bytes_total{topic}`, `capture_kafka_produce_avg_batch_size_{bytes,events}{topic}`.
- Queue: `capture_kafka_producer_queue_depth` / `_depth_limit`, `capture_kafka_producer_queue_bytes` / `_bytes_limit`, `capture_kafka_callback_queue_depth`.
- Brokers: `capture_kafka_any_brokers_down`, `capture_kafka_broker_connected{broker}`, `capture_kafka_broker_request_timeouts`, `capture_kafka_broker_requests_pending`, `capture_kafka_broker_responses_awaiting`, `capture_kafka_broker_tx_errors_total`, `capture_kafka_broker_rx_errors_total`, `capture_kafka_produce_{rtt,int,outbuf}_latency_us{broker,quantile}`.
- `capture_kafka_batch_prep_duration_seconds`, `capture_kafka_batch_enqueue_duration_seconds`. `capture_kafka_produce_errors_total` has a series only after a failure.

**Ingestion warnings** (`common/ingestion_warnings/src/`): `ingestion_warnings_total{path,source,type,outcome}` (`emitted`, `delivered`, `throttled`, …), `ingestion_warnings_throttle_keys`, `ingestion_warnings_emitter_enabled{reason}`.

## Redis dependencies

| Charts name                 | Env var                                         | ElastiCache (prod-us / prod-eu)                 | Used by                             | Health source                                                                                                                  |
| --------------------------- | ----------------------------------------------- | ----------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `posthog` (reader)          | `REDIS_URL`                                     | `posthog-solo` / `posthog-prod-redis-encripted` | billing limits, replay overflow set | `redis_*{job="redis", instance="prometheus-redis-exporter.monitoring.svc.cluster.local:9121"}`; EU also in `aws_elasticache_*` |
| `ingestion` (writer)        | `EVENT_RESTRICTIONS_REDIS_URL`                  | `ingestion-prod-redis`                          | event restrictions                  | `aws_elasticache_*{cache_cluster_id=~"ingestion-prod-redis.*"}`                                                                |
| `capture-globalratelimit`   | `GLOBAL_RATE_LIMIT_REDIS_URL` (+ `_READER_URL`) | `capture-globalratelimit-prod-redis`            | GRL shard 0 (analytics, ai)         | `aws_elasticache_*{cache_cluster_id=~"capture-globalratelimit-prod-redis.*"}`                                                  |
| `capture-globalratelimit-2` | `GLOBAL_RATE_LIMIT_REDIS_SHARD_1_URL`           | `capture-globalratelimit-2-prod-redis`          | GRL shard 1 (analytics only)        | `aws_elasticache_*{cache_cluster_id=~"capture-globalratelimit-2-prod-redis.*"}`                                                |
| edge, not capture           | —                                               | `ratelimit-prod-redis`                          | Contour per-IP rate limit           | `aws_elasticache_*{cache_cluster_id=~"ratelimit-prod-redis.*"}`                                                                |

- Replay has no GRL Redis. The bindings are the `redis:` blocks in charts `apps/capture-*/values.prod-*.yaml`.
- Useful `aws_elasticache_*` names: `engine_cpuutilization_average`, `database_memory_usage_percentage_average`, `curr_connections_average`, `evictions_sum`, `network_*_allowance_exceeded_sum`, `string_based_cmds_latency_average` (microseconds). Each node is its own `cache_cluster_id` (`-0`, `-001`, `-002`).
- EU has a second exporter, `prometheus-redis-exporter-cookieless`; capture does not use it.

## Edge: Envoy and the rate limit service

- Envoy metrics come from two ingress layers with the **same** `envoy_cluster_name`: `namespace="contour"` (main edge) and `namespace="proxy-as-a-service"` (managed reverse proxy). Always pick one.
- Clusters: `capture-analytics_capture-analytics_3000`, `capture-ai_capture-ai_3000`, `capture-replay_capture-replay_3000`. Status class label: `envoy_response_code_class` (`2`…`5`).
- Useful names: `envoy_cluster_upstream_rq_xx`, `envoy_cluster_upstream_rq_time_bucket`, `envoy_cluster_upstream_rq_timeout`, `envoy_cluster_upstream_rq_retry`, `envoy_cluster_membership_healthy` / `_total`, `envoy_cluster_upstream_cx_active`, `envoy_cluster_circuit_breakers_default_rq_open`, `envoy_cluster_upstream_rq_pending_overflow`.
- Edge rate limit (`ratelimit_service_*`, `namespace="contour"`): the capture-analytics event routes and capture-ai `/i/v0/ai/batch` and `/i/v1/ai` send a bare per-IP descriptor; replay sends none. Envoy answers 429 before capture sees the request.
  - Capture hits count under `key1="remote_address"` with no `key2`, so the metrics never name the IP. `key2="remote_address_<ip>"` appears only on per-route rules such as `key1="generic_key_feature-flags"`.
  - `ratelimit_service_rate_limit_over_limit{key1="remote_address"}` has no series until the first rejection. Compare against `ratelimit_service_rate_limit_total_hits{key1="remote_address"}`.
  - Thresholds: charts `argocd/ratelimit/values/values.prod-*.yaml`. Errors: `ratelimit_service_should_rate_limit_error{err_type}`.

## Kafka topics and backends

| Topic (prod-us / prod-eu)                                                                                                                                                                       | Producer                                                     | Backend (kminion instance)                  |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------- |
| `ingestion-analytics-main-1024` / `-512`, `ingestion-analytics-overflow-128`, `ingestion-analytics-historical-128`, `ingestion-analytics-team2-256` (US), `ingestion-analytics-turbo-1024` (US) | analytics, import                                            | MSK (`kminion-msk-ingestion`)               |
| `ingestion-heatmaps-main-128`, `ingestion-errortracking-main-128`, `ingestion-clientwarnings-main-16` / `-32`                                                                                   | analytics                                                    | MSK (`kminion-msk-ingestion`)               |
| `ingestion-ai-msk-128` / `-32`, `ingestion-ai-mskoverflow-32` / `-8`                                                                                                                            | analytics (`$ai_*` sent to legacy or v1 analytics endpoints) | MSK, bridged to WarpStream                  |
| `ingestion-ai-main-128` / `-32`, `ingestion-ai-overflow-32` / `-8`                                                                                                                              | capture-ai                                                   | WarpStream (`kminion-warpstream-ingestion`) |
| `ingestion-sessionreplay-main-512` / `-256`                                                                                                                                                     | replay                                                       | WarpStream (`kminion-warpstream-replay`)    |

- Read live topics with `sum by (namespace, topic) (increase(capture_kafka_produce_bytes_total[1h]))`.
- WarpStream producers carry `posthog_com_warpstream_client="true"` and large broker IDs; MSK brokers have small IDs.
- Topic lag and offsets: `kminion_kafka_*` with `app_kubernetes_io_instance` and `topic_name`.
- MSK CloudWatch metrics (`aws_kafka_*`, label `msk_cluster_name`) only cover the CDP intake cluster, not the ingestion cluster. There is no broker-side metric for the ingestion cluster; use the producer metrics above and kminion.

## Logs

- Loki labels: `namespace`, `container`, `pod`, `level` (`INFO`, `WARN`, `ERROR`), `service_name`, `target`. Lines are JSON.
- v1 lines carry the request context: `token`, `request_id`, `sdk_info`, `attempt`, `client_ip`, `path`, `error_tag`, `error`, with `target="capture::v1::analytics::handler"`.
- Common WARN lines (target): `events rate limited by distinct_id -- person processing disabled` (`capture::events::analytics`), `High GZIP compression ratio detected - potential GZIP bomb` (`capture::payload::decompression`), `Failed to update cache from Redis: Timeout` (`limiters::redis`), `Replica mget failed ..., falling back to primary` (`common_redis::read_write`).
- The INFO lines `handle_request called` and `process_batch called` may log every v1 request; filter on `level` or `error_tag` to skip them.

```logql
sum by (target, message) (count_over_time({namespace="capture-analytics", level=~"WARN|ERROR"} | json message="message", target="target" [1h]))
{namespace="capture-analytics"} | json | target=~"capture::v1::.*" | error_tag != ""
```

## Dashboards and alerts

| UID                                                                                                                               | Title                                      | Use for                                                |
| --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------ |
| `capture`                                                                                                                         | Capture                                    | Overview, start here (both regions)                    |
| `capture-v1-details`                                                                                                              | V1 Details                                 | v1 pipeline, GRL, restrictions, quota, GRL ElastiCache |
| `ddfkdj56ds11xce`                                                                                                                 | Legacy Details                             | Legacy pipeline, same shared sections                  |
| `posthog-alerts-capture-analytics`, `-capture-v1`, `-capture-grl`, `-capture-replay`, `-capture-import`, `posthog-alerts-contour` | Alerts: …                                  | Generated alert boards                                 |
| `ratelimit-posthog`                                                                                                               | Rate Limit Service                         | Edge rate limit                                        |
| `contour`, `envoy-contour-debug`                                                                                                  | Contour Ingress, Envoy / Contour Debugging | Edge                                                   |
| `dafu1z5geys4jkd`, `vm-redis`                                                                                                     | ElastiCache (Redis/Valkey), Redis          | Redis health                                           |
| `ingestion-health`, `ingestion-analytics`, `ingestion-ai`, `ingestion-sessionreplay`                                              | Ingestion boards                           | Downstream consumers                                   |

- V1 Details' "Kafka Production (V1 sink)" row queries `capture_v1_kafka_*` names that have no series; v1 publishes through the shared `capture_kafka_*` metrics. Its "v1 emits no warnings" note is also out of date.
- Alert rules and runbooks live in charts: `alerts/specs/capture-analytics.yaml`, `capture-v1.yaml`, `capture-grl.yaml`, `capture-replay.yaml`, `capture-import.yaml`, `contour.yaml`, with runbooks in `alerts/runbooks/<AlertName>.md`.

## Kubernetes and profiling

- Replicas: `kube_deployment_status_replicas{namespace=~"capture-(analytics|ai|replay|import)"}` by `deployment`. CPU and memory: `container_*{namespace=~"capture-(analytics|ai|replay|import)", container=~"capture-.*"}`.
- Pyroscope service names are `<namespace>/<container>` (for example `capture-analytics/capture-analytics`) plus `<namespace>-cilium/<container>` variants.

## Investigation playbooks

[references/investigation-playbooks.md](./references/investigation-playbooks.md) has step-by-step checks with tested queries: health, event loss (legacy and v1), latency, Kafka, quota and rate limiting, Redis, and cross-region comparison.
