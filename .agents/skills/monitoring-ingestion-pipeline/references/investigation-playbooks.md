# Investigation playbooks

Workflows for common ingestion pipeline investigations.
Each playbook describes **what to check and in what order** —
construct PromQL live using the discovery workflow from the main skill doc.

## 1. "Is ingestion healthy?" — quick health check

Start by pulling up the main dashboard:
`get_dashboard_by_uid` with uid `"ingestion-general"`.

Then verify these signals in order:

1. **E2E event lag** — `posthog_celery_observed_ingestion_lag_seconds{scenario="ingestion_api"}`.
   This is the Django-measured end-to-end lag from event capture to ClickHouse visibility.
   Sustained values > 60s warrant investigation.
2. **Consumer group lag** — `kminion_kafka_consumer_group_topic_lag_seconds` scoped to
   key groups: `ingestion-events`, `ingestion-events-overflow`, `session-recordings-blob-v2`.
   Growing lag = consumers falling behind.
3. **Pipeline results** — `ingestion_pipeline_results` by `result`.
   Watch for rising `dlq` or `dropped` rates relative to `ingested`.
4. **Pod restarts** — `kube_pod_container_status_restarts_total` for
   `namespace="posthog"`, `pod=~"ingestion-.*"`. Any recent restarts?
5. **ClickHouse consumer lag** — `kminion_kafka_consumer_group_topic_lag{group_id=~"clickhouse_events_json|group1|group1_recent", topic_name="clickhouse_events_json"}`.
   This is the final leg: even if ingestion workers are healthy, CH lag means users see stale data.
   (Consumer group name differs by env: `clickhouse_events_json` in prod-us, `group1`/`group1_recent` in prod-eu.)
6. **ClickHouse insert health** — `ClickHouseProfileEvents_FailedInsertQuery{type="events"}` rate.
   Non-zero = CH having trouble writing events.

## 2. "Events are being dropped" — pipeline result analysis

The pipeline result funnel tells you what happened to each event:

1. **Check result distribution** — `ingestion_pipeline_results` by `result`.
   Key values: `ingested`, `filtered`, `dropped`, `dlq`.
   Discover all values with `list_prometheus_label_values` on `result`.
2. **Check drop causes** — `ingestion_event_dropped_total` by `cause`.
   Discover live values with `list_prometheus_label_values` on `cause`.
3. **Check DLQ rate** — events sent to dead letter queue.
   Look at `ingestion_outputs_errors_total` by `topic` for DLQ topic production failures.
4. **Check overflow redirect** — `overflow_redirect_*` metrics.
   `overflow_redirect_decision` by `decision` shows whether events are being
   rerouted to overflow topics. This isn't a drop but changes the processing path.
5. **Per-pipeline breakdown** — scope all above by `ingestion_pipeline` and `ingestion_lane`
   to isolate which deployment is dropping events.

## 3. "Ingestion latency is high" — layered diagnosis

Diagnose layer by layer, from consumer to output:

1. **Consumer batch duration** — `consumed_batch_duration_ms` by `groupId`.
   This is the total time to consume + process a batch. High values mean slow processing.
   Compare across consumer groups to identify which pipeline is slow.

2. **Pipeline step latency** — `events_pipeline_step_ms` by `step_name`.
   Identify which step is the bottleneck. Common culprits:
   - `processPersonsStep` / `processGroupsStep` — database writes
   - `produceEventsStep` — Kafka production
   - `extractHeatmapDataStep` — CPU-intensive parsing

3. **Person store latency** — `person_*` metrics for flush duration and DB write time.
   `personhog_latency_seconds` for PersonHog gRPC call latency.
   Check `personhog_requests_total{status="error"}` for gRPC failures.

4. **Kafka production latency** — `ingestion_outputs_latency_seconds` by `topic`.
   Also `kafka_broker_rtt_us` by `broker_name` for broker-level RTT.

5. **Postgres latency** — no direct query latency metric; infer from:
   - Person flush time spikes correlating with `person_*` DB operation metrics
   - PgBouncer: `pgbouncer_*` metrics for connection pool saturation
   - CloudWatch RDS: CPU, read/write latency, connection count

## 4. "Consumer group lag is growing" — KMinion lag analysis

1. **Identify which group** — `kminion_kafka_consumer_group_topic_lag_seconds` by `group_id`.
   Check all ingestion consumer groups from the deployment roles table.
2. **Partition-level lag** — `kminion_kafka_consumer_group_topic_partition_lag` by `partition_id`.
   Uneven lag across partitions suggests a slow consumer pod or hot partition.
3. **Batch utilization** — `consumed_batch_duration_ms` vs configured max batch time.
   If batches are taking the full allowed time, the consumer is saturated.
4. **Consumer assignment** — `kafka_consumer_assignment` by `groupId`.
   Partitions should be evenly distributed. Zero = consumer not assigned.
5. **Rebalance events** — `consumer_background_task_timeout_total` for timeouts
   that trigger rebalances. Check Loki logs for rebalance messages:
   `{app=~"ingestion-events.*"} |= "rebalance"`.
6. **Backpressure from downstream** — if Kafka production to output topics is slow
   (`ingestion_outputs_latency_seconds` high), the consumer can't commit offsets fast enough.

## 5. "Person processing is slow" — person store diagnosis

1. **PersonHog gRPC health** — `personhog_requests_total` by `method` and `status`.
   Error rate, latency percentiles via `personhog_latency_seconds`.
   Connection state: `personhog_nodejs_grpc_connection_state`.
2. **Person cache** — `person_cache_*` metrics for hit/miss rates.
   Low hit rate = more DB lookups = higher latency.
3. **Person DB operations** — `person_*` metrics for flush duration, write mode
   (optimistic vs pessimistic), version mismatch conflicts.
   `person_update_version_mismatch` rate — high values = contention.
4. **Properties size** — `person_properties_size_bytes` histogram.
   Large person properties = slow reads/writes.
5. **Postgres health** — check PgBouncer metrics and CloudWatch RDS for the
   persons DB (`posthog-cloud-persons-prod-us-east-1`).
6. **Group processing** — `group_*` metrics for similar DB operation patterns.
   `group_update_version_mismatch` for optimistic update conflicts.

## 6. "Kafka / MSK problems" — broker and topic health

1. **Broker RTT** — `kafka_broker_rtt_us` by `broker_name` and `consumer_group`.
   Identify if a single broker is slow vs all brokers.
2. **Broker connectivity** — check for librdkafka error logs in Loki:
   `{app=~"ingestion-events.*"} |= "broker"`.
3. **MSK JMX metrics** — `list_prometheus_metric_names` regex `"aws_msk_kafka.*"`.
   Key signals: throttle time, network processor idle %, request queue size.
4. **WarpStream** — `warpstream_agent_*` metrics for WarpStream-backed topics.
   Scope to `warpstream-ingestion` namespace.
5. **KMinion cluster view** — dashboard `dbfgkwxs3gw8owd` for lag across all
   consumer groups and topics.
6. **Topic production** — `ingestion_outputs_message_value_bytes` by `topic` for
   output volume. Compare with consumption rate to find bottlenecks.

## 7. "Redis problems" — diagnosing Redis dependency failures

First, identify **which** Redis instance is affected:

| Symptom                                   | Likely instance  |
| ----------------------------------------- | ---------------- |
| `overflow_redirect_redis_*` errors rising | Ingestion Redis  |
| `cookieless_redis_error` rising           | Cookieless Redis |
| Overflow decisions reverting to defaults  | Ingestion Redis  |
| Person deduplication failures             | Dedup Redis      |

Then check infrastructure health:

1. **CloudWatch ElastiCache** — datasource `P034F075C744B399F`.
   Key metrics: `EngineCPUUtilization`, `DatabaseMemoryUsagePercentage`,
   `CurrConnections`, `Evictions`, `ReplicationLag`.
   Cluster IDs: `ingestion-prod-redis`, `posthog-solo` (prod-us primary),
   `cookieless-prod-redis`, `ingestion-duplicates-prod-redis`.
   prod-eu primary: `posthog-prod-redis-encripted` (sic).
2. **Loki logs** — `{app=~"ingestion-events.*"} |= "redis" |= "error"`.
3. **Fail-open behavior** — ingestion workers are generally designed to fail open
   for Redis failures, but overflow routing accuracy degrades.

## 8. "Postgres problems" — database health

1. **Ingestion-side signals** — `postgres_error_total` by `operation`.
   `person_update_version_mismatch` / `group_update_version_mismatch` for contention.
2. **PgBouncer** — `pgbouncer_*` metrics for connection pool utilization,
   waiting clients, query duration. Scope to the ingestion PgBouncer instances:
   `ingestion-default-pgbouncer` (main) and `ingestion-events-pgbouncer` (persons).
3. **CloudWatch RDS** — datasource `P034F075C744B399F`.
   Cluster IDs: `posthog-cloud-prod-us-east-1` (main), `posthog-cloud-persons-prod-us-east-1` (persons).
   Key metrics: `CPUUtilization`, `ReadLatency`, `WriteLatency`, `DatabaseConnections`.
4. **Postgres exporter** — `list_prometheus_metric_names` regex `"pg_.*"`.
   `prometheus-postgres-exporter` and `prometheus-postgres-persons-exporter`.
5. **Loki logs** — `{app=~"ingestion-events.*"} |= "postgres" |= "error"` or
   `{app=~"ingestion-events.*"} |= "ECONNREFUSED"`.

## 9. "Session replay ingestion issues" — replay pipeline

1. **Replay-specific dashboard** — `get_dashboard_by_uid` with uid `"ingestion-session-recordings"`.
2. **Consumer lag** — `kminion_kafka_consumer_group_topic_lag_seconds{group_id="session-recordings-blob-v2"}`.
3. **Replay metrics** — `list_prometheus_metric_names` regex `"recording_blob_ingestion_v2_.*"`.
   Key: batch size, S3 upload latency, session manager operations.
4. **K8s resources** — scope to `app="recordings-blob-ingestion-v2"`.
5. **Pyroscope** — profile `recordings/recordings-blob-ingestion-v2` for CPU/memory hotspots.

## 10. "ClickHouse ingestion is behind" — downstream health

ClickHouse lag means users see stale data even if ingestion workers are healthy.

1. **Consumer lag on `clickhouse_events_json`** —
   `kminion_kafka_consumer_group_topic_lag{group_id=~"clickhouse_events_json|group1|group1_recent", topic_name="clickhouse_events_json"}`.
   Also check `kminion_kafka_consumer_group_topic_lag_seconds` for time-based lag.
   (Consumer group name differs by env: `clickhouse_events_json` in prod-us, `group1`/`group1_recent` in prod-eu.)
   Dashboard: `dbfgkwxs3gw8owd` (KMinion Consumer Group Lag).

2. **CH Kafka engine errors** — `ClickHouseProfileEvents_KafkaRowsRejected{type="events"}` rate.
   Also `ClickHouseProfileEvents_KafkaConsumerErrors` and `KafkaCommitFailures`.
   Non-zero rejection rate = CH can't parse/insert some rows (schema mismatch, data issues).

3. **Insert failures** — `ClickHouseProfileEvents_FailedInsertQuery{type="events"}` rate.
   May indicate too-many-parts errors, memory pressure, or schema issues.

4. **Part count growth** — `ClickHouseAsyncMetrics_MaxPartCountForPartition{type="events"}`.
   Rising steadily = merge thread can't keep up with insert rate.
   CH hard-limits at 300 parts per partition — approaching this causes insert rejects.
   Dashboard: `ef7h2todfg4xsd` (merge overview).

5. **Merge pressure** — `ClickHouseMetrics_BackgroundMergesAndMutationsPoolTask{type="events"}`.
   Compare to pool size. Also `ClickHouseProfileEvents_MergedRows` rate.

6. **Readonly replicas** — `ClickHouseMetrics_ReadonlyReplica{type="events"}`.
   Non-zero = a replica fell behind and can't accept writes.

7. **Replication delay** — `ClickHouseAsyncMetrics_ReplicasMaxAbsoluteDelay{type="events"}`.
   High delay = inter-shard replication lagging.

8. **Kafka Connect health** (DuckLake path) —
   `kafka_connect_connect_worker_metrics_connector_failed_task_count{namespace="kafka-connect"}`.
   Also `kafka_connect_ducklake_sink_task_metrics_ducklake_records_processed` for throughput
   and `ducklake_errant_record_count` for DLQ'd records.
   Dashboard: `cdzv7o1635n9ca` (Kafka Connect).

9. **CH ingestion pod resources** — dashboard `8aa35a4a-091a-4645-ac8f-ae46901f0060`.
   CPU throttling, memory pressure, disk usage on `chi-ingestion-*` pods in the
   `clickhouse` namespace.

10. **CH cluster overview** — dashboard `vm-clickhouse-cluster-overview`.
    QPS, memory tracking, disk capacity, connection count, ZooKeeper health.

## 11. "Comparing prod-us vs prod-eu" — cross-environment

Most ingestion app metrics use the `app` / `ingestion_pipeline` labels but
**no environment label** — the environment is implicit in which Grafana you're connected to.

For cross-environment comparison:

1. **Same queries, different Grafana** — run the same PromQL against both environments
   by switching the Grafana MCP connection (requires a new session).
2. **Dashboard UIDs are synced** — all dashboards above exist in both environments
   with the same UIDs (deployed from shared `Synced` folder).
   Exception: `deoz13wy08wsga` (ClickHouse disk capacity EU ONLY).
3. **Label values are identical** — `ingestion_pipeline`, `ingestion_lane`, ClickHouse `type`
   values are the same across envs.
4. **CloudWatch cluster IDs differ** — use the env-specific names from the topology sections:
   - Redis: `posthog-solo` (US) vs `posthog-prod-redis-encripted` (EU) for primary
   - MSK: `posthog-prod-us-events-*` vs `posthog-prod-eu-events-*`
   - RDS: `posthog-cloud-prod-us-east-1` vs `posthog-cloud-prod-eu-central-1`
5. **Deployment differences** — `ingestion-general-turbo` exists only in **prod-us**.
