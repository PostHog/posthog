# Investigation playbooks

Workflows for common capture service investigations.
Each playbook describes **what to check and in what order** —
construct PromQL live using the discovery workflow from the main skill doc.

## 1. "Is capture healthy?" — quick health check

Start by pulling up the main dashboard:
`get_dashboard_by_uid` with uid `"capture"`.

Then verify these signals in order:

1. **HTTP error rate** — `http_requests_duration_seconds_count` by `status`, role-scoped.
   Any sustained 5xx spike is the top-priority signal.
2. **Kafka connectivity** — `capture_kafka_any_brokers_down`. Value of 1 on any pod is critical.
3. **Event acceptance ratio** — `rate(capture_events_ingested_total)` / `rate(capture_events_received_total)`.
   Sustained drop below ~0.95 warrants investigation.
4. **Envoy backend health** — `envoy_cluster_membership_healthy` vs `envoy_cluster_membership_total`
   for `envoy_cluster_name=~"posthog_capture.*"`. Ratio < 1.0 outside of deploys is a problem.
5. **Event restrictions staleness** — `capture_event_restrictions_stale` gauge.
   Value of 1 means restrictions aren't being refreshed from Redis.
6. **Billing limits loaded** — `capture_billing_limits_loaded_tokens` by `cache_key`.
   Zero for any cache key means quota limits aren't loading.

## 2. "Events are being lost" — event lifecycle funnel

The event funnel: received -> ingested -> dropped/rerouted.

1. **Compare rates** — `rate(capture_events_received_total)` vs `rate(capture_events_ingested_total)`.
   The gap is drops + reroutes.
2. **Discover drop causes** — `capture_events_dropped_total` by `cause`.
   Discover live values with `list_prometheus_label_values` on `cause`.
   Key causes to watch:
   - `retryable_sink` — Kafka producer failures (check Kafka health next)
   - `events_over_quota` / `recordings_over_quota` / `*_over_quota` — billing limits hit
   - `token_dropper` — token-level restriction
   - `kafka_message_size` — individual event too large for Kafka
   - `no_distinct_id` / `no_event_name` — malformed events from SDKs
3. **Check Kafka delivery** — `capture_kafka_produce_errors_total` rate.
   Non-zero = messages failing to produce.
4. **Check quota limits** — `capture_quota_limit_exceeded` by `resource`.
5. **Check event restrictions** — `capture_event_restrictions_applied` by `restriction_type`.
   `drop_event` directly causes loss; `force_overflow` reroutes to overflow topic.
6. **Check rerouting** — `capture_events_rerouted_overflow` by `reason`.
   Events rerouted aren't lost but take a different path through the pipeline.

## 3. "Latency is high" — layered diagnosis

Diagnose layer by layer, outside-in:

1. **Envoy layer** — `envoy_cluster_upstream_rq_time_bucket` histogram for
   `envoy_cluster_name=~"posthog_capture.*"`.
   Compute p99 with `histogram_quantile(0.99, ...)`.
   If Envoy latency is high but HTTP handler latency is normal, the issue is between Envoy and the pod (networking, connection pool).

2. **HTTP handler** — `http_requests_duration_seconds_bucket` scoped by `role`.
   This is the end-to-end request latency inside the capture binary.
   Compare p99 across roles to isolate which pipeline is slow.

3. **Kafka produce RTT** — `capture_kafka_produce_rtt_latency_us` by `broker` and `quantile`.
   p99 > 100ms sustained = broker overload or network issues.
   p99 > 500ms = critical.
   Cross-reference with queue depth for backpressure signal.

4. **Redis latency** — no direct latency metric in capture.
   Check `capture_event_restrictions_redis_fetch{result="error"}` rate as a proxy.
   For actual Redis latency, use CloudWatch ElastiCache metrics via datasource `P034F075C744B399F`.

5. **Kafka producer queue depth** — `capture_kafka_producer_queue_depth` / `capture_kafka_producer_queue_depth_limit`.
   Ratio > 0.8 = producer near saturation, will backpressure the HTTP handler.

## 4. "Kafka backpressure" — producer saturation

1. **Queue saturation** — `capture_kafka_producer_queue_depth` / `capture_kafka_producer_queue_depth_limit`.
   Also check bytes: `capture_kafka_producer_queue_bytes` / `_bytes_limit`.
2. **Broker RTT** — `capture_kafka_produce_rtt_latency_us{quantile="p99"}` by `broker`.
   Identify if a single broker is slow vs all brokers.
3. **Broker connectivity** — `capture_kafka_broker_connected` by `broker`.
   Any broker at 0 across all pods needs immediate investigation.
4. **Broker errors** — `capture_kafka_broker_tx_errors_total` and `_rx_errors_total` by broker.
   `capture_kafka_broker_request_timeouts` by broker.
5. **MSK throttle time** — discover `aws_msk_*` metrics with
   `list_prometheus_metric_names` regex `"aws_msk_kafka.*throttle.*"`.
   Throttling means Kafka quota enforcement is active.
6. **MSK network processor** — look for idle % metric.
   < 30% idle = broker network thread saturation warning.
7. **Topic-level** — `capture_kafka_produce_avg_batch_size_bytes` and `_events` by `topic`.
   Identify which topic is receiving the most load.
8. **Downstream impact** — `overflow_redirect_*` metrics on the Node.js ingestion pipeline.
   These are NOT capture metrics but show how overflow topics are being consumed.

## 5. "Rate limiting / quota impact" — which limiters are active

Multiple layers of rate limiting can affect capture. Check in this order:

1. **Billing quota** (per-team, Redis-backed)
   - `capture_quota_limit_exceeded` by `resource` — which quota types are being hit
   - `capture_billing_limits_loaded_tokens` by `cache_key` — how many tokens are flagged
   - Drop causes: `events_over_quota`, `recordings_over_quota`, `exceptions_over_quota`,
     `llm_events_over_quota`, `survey_responses_over_quota` on `capture_events_dropped_total`

2. **Event restrictions** (per-team, Redis-backed)
   - `capture_event_restrictions_applied` by `restriction_type`
   - `drop_event` = hard drop, `force_overflow` = reroute to overflow topic,
     `redirect_to_topic` = reroute to custom topic, `skip_person_processing` = pass through but skip person

3. **Global rate limiter** (per-token+distinct_id, Redis-backed)
   - Code defines `global_rate_limiter_*` metrics but they may not be active.
     Check `list_prometheus_metric_names` regex `"global_rate_limiter.*"` first.
   - Proxy signal: `capture_events_rerouted_overflow{reason="rate_limited"}` rate.
   - Config: `GLOBAL_RATE_LIMIT_ENABLED`, `GLOBAL_RATE_LIMIT_TOKEN_DISTINCTID_THRESHOLD`

4. **Overflow routing** (the combined effect)
   - `capture_events_rerouted_overflow` by `reason`:
     `rate_limited` (GRL), `force_limited` (event restrictions), `event_restriction` (explicit overflow)

5. **Contour rate limit** (per-IP, Envoy-layer, NOT capture binary)
   - `ratelimit_service_rate_limit_over_limit` — actively limited IPs
   - `ratelimit_service_rate_limit_total_hits` — total evaluations
   - Labels: `domain="posthog"`, `key1`, `key2` for rule identification
   - This Redis (`ratelimit-{env}-redis`) is separate from capture's Redis instances

## 6. "Redis problems" — diagnosing Redis dependency failures

First, identify **which** Redis instance is affected:

| Symptom                                                           | Likely instance                        |
| ----------------------------------------------------------------- | -------------------------------------- |
| `capture_event_restrictions_redis_fetch{result="error"}` rising   | Primary or event restrictions Redis    |
| `capture_event_restrictions_stale` = 1                            | Primary or event restrictions Redis    |
| `capture_billing_limits_loaded_tokens` = 0 for a `cache_key`      | Primary Redis                          |
| `capture_events_rerouted_overflow{reason="rate_limited"}` anomaly | GRL Redis                              |
| `ratelimit_service_*` errors                                      | Contour rate limit Redis (not capture) |

Then check infrastructure health:

1. **CloudWatch ElastiCache** — use datasource `P034F075C744B399F`.
   Key metrics: `EngineCPUUtilization`, `DatabaseMemoryUsagePercentage`,
   `CurrConnections`, `Evictions`, `ReplicationLag`.
   Cluster IDs:
   - Primary: `posthog-solo` (prod-us) or `posthog-prod-redis-encripted` (prod-eu; sic — typo in actual name)
   - GRL: `capture-globalratelimit-prod-redis`
   - Rate limit: `ratelimit-prod-redis`

2. **prometheus-redis-exporter** — search VictoriaMetrics for Redis exporter metrics
   if available: `list_prometheus_metric_names` regex `"redis_.*"`.

3. **Fail-open behavior** — capture is designed to fail open for most Redis failures:
   - Quota limiter: if Redis is down, limits aren't refreshed but cached limits still apply
   - Event restrictions: `event_restrictions_fail_open_after_secs` config controls
     how long after a Redis failure before restrictions are bypassed
   - GRL: if Redis is down, rate limiting stops (traffic passes through)

## 7. "Comparing prod-us vs prod-eu" — cross-environment

Most capture app metrics use the `role` label but **no environment label** —
the environment is implicit in which Grafana instance you're connected to.

For cross-environment comparison:

1. **MSK metrics** use `environment="prod-us"` or `"prod-eu"` label — these can be
   compared in a single query.
2. **CloudWatch** datasource has access to both regions — use region selector
   in the query.
3. **Dashboard variables** — some dashboards have an `environment` variable.
   Check with `get_dashboard_by_uid` and look at template variables.
4. **Kafka topic names** are the same across environments — the topic label works
   for comparing produce patterns.
