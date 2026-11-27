# Investigation playbooks

Each step names a query that ran against prod-us and prod-eu. Scope app metrics to `namespace=~"capture-(analytics|ai|replay|import)"` (shortened below to `$capture`) or to one namespace.
Run the PromQL as written through `query-metrics` (PostHog MCP) or `query_prometheus` on datasource `victoriametrics` (Grafana MCP). Logs use `query-logs` or Loki datasource `P44D702D3E93867EC`.

## 1. Is capture healthy?

1. **Edge success** (both pipelines, cannot split by route):
   `sum by (envoy_cluster_name, envoy_response_code_class) (rate(envoy_cluster_upstream_rq_xx{namespace="contour", envoy_cluster_name=~"capture-(analytics|ai|replay)_.*"}[5m]))`
2. **Legacy errors**: `sum by (namespace, status) (rate(http_requests_total{namespace=~"$capture", path!~"/i/v1/.*"}[5m]))`
3. **v1 errors and outcomes**: `sum by (namespace, error, status_code) (rate(capture_v1_analytics_error{namespace=~"$capture"}[5m]))` and `sum by (namespace, outcome) (rate(capture_v1_batch_outcomes[5m]))`. A steady `billing_limit_exceeded` (402) and a trickle of `missing_required_headers` (400) are normal.
4. **Kafka**: `max by (namespace) (capture_kafka_any_brokers_down)` must be 0, and `max by (namespace) (capture_kafka_producer_queue_depth / capture_kafka_producer_queue_depth_limit)` well under 0.8.
5. **Backends up**: `min by (envoy_cluster_name) (envoy_cluster_membership_healthy{namespace="contour", envoy_cluster_name=~"capture-(analytics|ai|replay)_.*"} / envoy_cluster_membership_total{namespace="contour", envoy_cluster_name=~"capture-(analytics|ai|replay)_.*"})`, below 1 outside a deploy is a problem.
6. **Shared state loaded**: `max by (namespace, pipeline) (capture_event_restrictions_stale{namespace=~"$capture"})` = 0, and `max by (namespace, cache_key) (capture_billing_limits_loaded_tokens{namespace=~"$capture"})` above 0 for every `@posthog/quota-limits/*` key.
7. **GRL evaluating**: `sum by (namespace, scope, result) (rate(global_rate_limiter_eval_counts_total[5m]))` has `allowed` traffic for each scope.

## 2. Events are being lost

Pick the pipeline first; the counters differ.

**Legacy**

1. In versus out: `sum by (namespace) (rate(capture_events_received_total{namespace=~"$capture"}[5m]))` against `sum by (namespace) (rate(capture_events_ingested_total{namespace=~"$capture"}[5m]))`. Ingested also counts v1 and reroutes, so read the gap as a trend, not a balance.
2. Why: `sort_desc(sum by (namespace, cause) (increase(capture_events_dropped_total{namespace=~"$capture"}[1h])))`. Quota causes (`*_over_quota`) dominate normally; new or growing `kafka_message_size`, `event_too_big` or `token_dropper` are worth a look.
3. Request-level failures: `sum by (namespace, stage, error) (increase(capture_error_by_stage_and_type[1h]))`.

**v1**

1. Per-request outcome: `sum by (namespace, path, outcome) (increase(capture_v1_batch_outcomes[1h]))`. `partial_failure`, `all_drop` and `all_retry` carry per-event results back to the SDK.
2. Per-event drops: `sum by (namespace, reason, stage) (increase(capture_v1_events_dropped[1h]))` and `sum by (namespace, result) (increase(capture_v1_parsed_events[1h]))`.
3. Whole-request rejections: `sum by (namespace, error, status_code) (increase(capture_v1_analytics_error[1h]))`.
4. Silent loss, absent until it happens: `capture_v1_serialize_failed_total`, `capture_v1_serialize_panic_total`.

**Both**

- Kafka delivery: `sum by (namespace, topic, outcome) (rate(capture_kafka_produce_ack_duration_ms_count{namespace=~"$capture"}[5m]))`. `dropped` means the delivery future was abandoned.
- Restrictions that drop: `sum by (namespace, pipeline, restriction_type) (increase(capture_event_restrictions_applied[1h]))` (both pipelines) and `capture_v1_events_restricted{action}` (v1).
- Reroutes are not loss: `capture_events_rerouted_overflow{reason}`, `capture_events_rerouted_custom_topic`, `capture_v1_events_rerouted_historical{reason}`.

## 3. Latency is high

Outside in:

1. Edge p99: `histogram_quantile(0.99, sum by (le, envoy_cluster_name) (rate(envoy_cluster_upstream_rq_time_bucket{namespace="contour", envoy_cluster_name=~"capture-(analytics|ai|replay)_.*"}[5m])))` (milliseconds).
2. In-process, legacy: `histogram_quantile(0.99, sum by (le, namespace) (rate(http_requests_duration_seconds_bucket{namespace=~"$capture", path!~"/i/v1/.*"}[5m])))`.
3. In-process, v1: `histogram_quantile(0.99, sum by (le, namespace, path) (rate(capture_v1_response_time_seconds_bucket[5m])))` and `max by (namespace, quantile) (capture_v1_processing_duration_seconds)`.
4. Kafka round trip: `max by (namespace, broker) (capture_kafka_produce_rtt_latency_us{quantile="p99"})` and queue depth from playbook 1.
5. If the edge is slow and the app is not, look at Envoy (`envoy_cluster_upstream_rq_timeout`, `envoy_cluster_upstream_rq_pending_overflow`) and pod CPU (`container_cpu_usage_seconds_total{namespace=~"$capture"}`).

## 4. Kafka or WarpStream backpressure

1. Queue: `max by (namespace) (capture_kafka_producer_queue_depth / capture_kafka_producer_queue_depth_limit)` and the `_bytes` pair.
2. One broker or all: `max by (namespace, broker) (capture_kafka_produce_rtt_latency_us{quantile="p99"})`, `sum by (namespace, broker) (rate(capture_kafka_broker_request_timeouts[5m]))`, `min by (namespace, broker) (capture_kafka_broker_connected)`.
3. Which topic: `sum by (namespace, topic) (rate(capture_kafka_produce_bytes_total[5m]))`.
4. Backend: capture-analytics and capture-import produce to MSK (`kminion-msk-ingestion`); capture-ai and capture-replay to WarpStream (`kminion-warpstream-ingestion`, `kminion-warpstream-replay`). There is no broker-side metric for the MSK ingestion cluster; `aws_kafka_*` covers only the CDP intake cluster.
5. Downstream lag: `sum by (app_kubernetes_io_instance, topic_name) (kminion_kafka_consumer_group_topic_lag{topic_name=~"ingestion-.*"})`.

## 5. Quota, restrictions and rate limits

Layers in request order:

1. **Edge per-IP limit** (Contour, before capture, answers 429): `sum(increase(ratelimit_service_rate_limit_over_limit{namespace="contour", key1="remote_address"}[1h]))` against the same on `ratelimit_service_rate_limit_total_hits`. No series means no rejections. The metric does not name the IP. Errors: `ratelimit_service_should_rate_limit_error{err_type}`.
2. **Billing quota**:
   - Legacy: `sum by (namespace, resource) (increase(capture_quota_limit_exceeded[1h]))`
   - v1: `sum by (namespace, resource) (increase(capture_v1_events_quota_limited[1h]))`, plus whole-request 402s in `capture_v1_analytics_error{error="billing_limit_exceeded"}`
   - Tokens flagged: `max by (namespace, cache_key) (capture_billing_limits_loaded_tokens)`
3. **Event restrictions**: `capture_event_restrictions_applied{pipeline,restriction_type}`, staleness and loaded counts per `pipeline`. Stale means capture fails open and applies nothing.
4. **Global rate limiter**:
   - Decisions: `sum by (namespace, scope, result) (rate(global_rate_limiter_eval_counts_total[5m]))`
   - App effect: `capture_v1_rate_limiter{outcome}` (v1), `capture_events_rate_limited_token_distinctid{reason}` (legacy)
   - Health: `sum by (namespace, scope, step, cause, redis_idx) (increase(global_rate_limiter_error_total[1h]))`, `max by (namespace, scope, redis_idx) (global_rate_limiter_read_failing_seconds)`, `max by (namespace, scope) (global_rate_limiter_update_channel_depth)`
5. **AI byte budget**: GRL scopes `events_ai_bytes` (capture-analytics) and `ai_ai_bytes` (capture-ai), and the legacy drop cause `ai_byte_rate_limited`.
6. **Overflow**: `sum by (namespace, reason) (increase(capture_events_rerouted_overflow[1h]))`.

## 6. Redis problems

Find the instance from the symptom, then check its health source (table in SKILL.md).

| Symptom                                                                                                               | Instance                                  |
| --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `Failed to update cache from Redis` (`target="limiters::redis"`), billing tokens stop changing                        | primary `posthog` reader                  |
| `capture_event_restrictions_redis_fetch{result=~"error\|parse_error"}` rising, `capture_event_restrictions_stale` = 1 | `ingestion-prod-redis`                    |
| `global_rate_limiter_error_total` or `global_rate_limiter_read_failing_seconds` rising for a `redis_idx`              | GRL shard 0 or 1                          |
| `ratelimit_service_should_rate_limit_error{err_type="redis_error"}`                                                   | edge `ratelimit-prod-redis` (not capture) |

- Primary, US: `redis_connected_clients{job="redis", instance="prometheus-redis-exporter.monitoring.svc.cluster.local:9121"}` and other `redis_*` exporter metrics.
- Others: `max by (cache_cluster_id) (aws_elasticache_engine_cpuutilization_average{cache_cluster_id=~"capture-globalratelimit.*"})`, and the same with `database_memory_usage_percentage_average`, `evictions_sum`, `curr_connections_average`.
- What fails open: billing keeps its last loaded set; restrictions apply nothing once stale (default 300 s); the GRL skips limits for keys whose Redis shard is in a read outage (`global_rate_limiter_outage_limit_skipped_total`, absent until it fires).

## 7. prod-us versus prod-eu

- Run the same query through each region's tools; `environment` only labels series.
- Topic names differ by partition count (`ingestion-analytics-main-1024` in US, `-512` in EU), so compare by `namespace` or a topic regex.
- Replica counts differ (EU runs fewer pods), so compare per-pod rates or ratios, not sums.
- EU's primary Redis (`posthog-prod-redis-encripted`, spelled that way) is also in `aws_elasticache_*`; US `posthog-solo` is only in the Redis exporter.
