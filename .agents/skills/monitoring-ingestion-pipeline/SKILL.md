---
name: monitoring-ingestion-pipeline
description: >
  Guide for using the Grafana MCP to monitor and diagnose the Node.js ingestion
  pipeline workers in production. Use when investigating event lag, drops,
  pipeline errors, person/group processing, Kafka consumer health, Redis,
  Postgres, ClickHouse downstream health, or any ingestion worker question.
  Covers prod-us and prod-eu environments.
---

# Monitoring the ingestion pipeline with Grafana MCP

The ingestion pipeline (`nodejs/`) is PostHog's Node.js event processing layer.
It consumes events from Kafka (produced by the capture service), runs them through
processing steps (person resolution, group assignment, property overrides, etc.),
and produces enriched events to ClickHouse-bound Kafka topics.

A single codebase is deployed as **many K8s Deployments** via the `posthog-node`
Helm chart. Each deployment sets `PLUGIN_SERVER_MODE` and is distinguished in
metrics by two default Prometheus labels:

- `ingestion_pipeline` — values: `general`, `heatmaps`, `client_warnings`, `errortracking`
- `ingestion_lane` — values: `main`, `overflow`, `historical`, `async`

The `app` label (set by K8s) matches the deployment name and is the most
universal scope filter across all telemetry domains.

This skill teaches how to **discover live metrics** using the Grafana MCP tools
rather than memorizing metric names that change as the code evolves.

## Environment context

The Grafana MCP is connected to a **single Grafana instance** scoped to one environment.
If the user hasn't specified, **ask which environment** they want to investigate:

- **prod-us** — US production (us-east-1)
- **prod-eu** — EU production (eu-central-1)

Most ingestion app metrics are environment-specific by virtue of which Grafana
you're connected to — they don't carry an `environment` label. CloudWatch metrics
are also scoped to the connected Grafana's AWS account.

Cross-environment comparison requires switching Grafana instances (not possible in one session).

All datasource UIDs, dashboard UIDs, `ingestion_pipeline`/`ingestion_lane` label values,
and ClickHouse `type` label values are **identical** across prod-us and prod-eu.

Key differences:

- `ingestion-general-turbo` deployment exists only in **prod-us**.
- CloudWatch cluster IDs differ by region suffix (see topology sections below).

## Observability landscape

Six telemetry domains, all validated identical across prod-us and prod-eu:

| Domain                             | Datasource UID                  | Discovery tool                 | Scope filter                              |
| ---------------------------------- | ------------------------------- | ------------------------------ | ----------------------------------------- |
| App metrics (VictoriaMetrics)      | `victoriametrics`               | `list_prometheus_metric_names` | See metric prefixes below                 |
| App metrics (realtime)             | `victoriametrics-realtime`      | same                           | same (lower retention, higher resolution) |
| Logs                               | `P44D702D3E93867EC` (Loki-logs) | `list_loki_label_names`        | `app=~"ingestion-.*"`                     |
| Profiling                          | `pyroscope`                     | `list_pyroscope_profile_types` | See Pyroscope services below              |
| CloudWatch (ElastiCache, MSK, RDS) | `P034F075C744B399F`             | `query_prometheus`             | env-specific cluster IDs                  |
| Dashboards                         | n/a                             | `search_dashboards`            | query `"ingestion"` or deployment name    |

**Datasource notes:**

- Do NOT use primary Loki (`P8E80F9AEF21F6940`) — it returns 502 intermittently in both envs. Always use **Loki-logs** (`P44D702D3E93867EC`).
- Do NOT use `CloudWatch Root` (`PAAE47F430CFD1449`) — it exists only in prod-us.

## Stable waypoints

These facts change infrequently and are hard to discover dynamically.

### Deployment roles

All `PLUGIN_SERVER_MODE=ingestion-v2` deployments (the "analytics ingestion" family), plus specialized modes:

| Deployment name                | Mode                           | Lane         | Consumer group                | Consume topic pattern                       |
| ------------------------------ | ------------------------------ | ------------ | ----------------------------- | ------------------------------------------- |
| `ingestion-events`             | `ingestion-v2`                 | `main`       | `ingestion-events`            | `ingestion-events-{partitions}`             |
| `ingestion-events-overflow`    | `ingestion-v2`                 | `overflow`   | `ingestion-events-overflow`   | `ingestion-events-overflow-{partitions}`    |
| `ingestion-events-historical`  | `ingestion-v2`                 | `historical` | `ingestion-events-historical` | `ingestion-events-historical-{partitions}`  |
| `ingestion-events-async`       | `ingestion-v2`                 | `async`      | `ingestion-events-async`      | `events_plugin_ingestion_async`             |
| `ingestion-client-warnings`    | `ingestion-v2`                 | —            | `ingestion-client-warnings`   | `client_iwarnings_ingestion`                |
| `ingestion-heatmaps`           | `ingestion-v2`                 | —            | `ingestion-heatmaps`          | `heatmaps_ingestion`                        |
| `ingestion-general-turbo`      | `ingestion-v2`                 | —            | `ingestion-general-turbo`     | `ingestion-general-turbo-{partitions}`      |
| `ingestion-batch-imports`      | `ingestion-v2`                 | —            | `ingestion-batch-imports`     | `ingestion-batch-imports`                   |
| `ingestion-logs`               | `ingestion-logs`               | —            | `ingestion-logs`              | `logs_ingestion`                            |
| `ingestion-errortracking-main` | `ingestion-errortracking`      | —            | `ingestion-errortracking`     | `ingestion-errortracking-main-{partitions}` |
| `recordings-blob-ingestion-v2` | `recordings-blob-ingestion-v2` | —            | `session-recordings-blob-v2`  | `session_recording_snapshot_item_events`    |

**Note:** `ingestion-general-turbo` exists only in **prod-us**.

### Metric prefixes

Every prefix here can be discovered live with `list_prometheus_metric_names`
using `datasourceUid: "victoriametrics"` and `regex: "<prefix>.*"`.

| Prefix                                                                           | Domain                                     | Key scope labels                                   |
| -------------------------------------------------------------------------------- | ------------------------------------------ | -------------------------------------------------- |
| `ingestion_*`                                                                    | Core ingestion app metrics (~80 metrics)   | `app`, `ingestion_pipeline`, `ingestion_lane`      |
| `consumed_batch_*`                                                               | Kafka consumer batch processing            | `topic`, `groupId`                                 |
| `consumer_batch_*` / `consumer_background_*`                                     | Consumer loop health                       | `topic`, `groupId`                                 |
| `kafka_broker_*`                                                                 | librdkafka broker stats                    | `broker_id`, `broker_name`, `consumer_group`       |
| `kafka_consumer_*`                                                               | Consumer rebalance, assignment             | `groupId`, `type`                                  |
| `events_pipeline_*`                                                              | Legacy pipeline step metrics               | `step_name`                                        |
| `person_*`                                                                       | Person processing (~30 metrics)            | `db_write_mode`, `operation`, `method`             |
| `group_*` (non-AWS)                                                              | Group processing                           | `operation`                                        |
| `personhog_*`                                                                    | PersonHog gRPC client + service            | `method`, `source`, `client`                       |
| `overflow_redirect_*`                                                            | Stateful overflow routing                  | `type`, `result`, `decision`, `operation`          |
| `cookieless_*`                                                                   | Cookieless mode                            | —                                                  |
| `http_request_duration_seconds`                                                  | HTTP health/readiness server               | `method`, `route`, `status_code`                   |
| `recording_blob_ingestion_v2_*`                                                  | Session replay ingestion                   | `app`                                              |
| `logs_ingestion_*`                                                               | Logs ingestion pipeline                    | `app`                                              |
| `error_tracking_*` / `cymbal_*`                                                  | Error tracking pipeline                    | `app`                                              |
| `kminion_kafka_*`                                                                | KMinion consumer group lag & topic offsets | `group_id`, `topic_name`, `partition_id`           |
| `aws_msk_kafka_*`                                                                | MSK broker-side JMX metrics                | `environment`                                      |
| `warpstream_agent_*`                                                             | WarpStream agent metrics                   | varies                                             |
| `kube_*` / `container_*`                                                         | K8s resources                              | `namespace="posthog"`, `container=~"ingestion-.*"` |
| `pg_*` / `pgbouncer_*`                                                           | Postgres exporter                          | varies                                             |
| `ClickHouseMetrics_*` / `ClickHouseProfileEvents_*` / `ClickHouseAsyncMetrics_*` | ClickHouse cluster health                  | `type` (=cluster role)                             |
| `kafka_connect_*`                                                                | Kafka Connect bridge to ClickHouse         | `namespace`, `connector`                           |
| `posthog_celery_clickhouse_*`                                                    | CH health monitors from Django celery      | `scenario`                                         |

### Redis topology

Ingestion workers depend on up to five Redis instances.
Redis health is inferred from ingestion-side metrics and CloudWatch ElastiCache metrics.

| Redis instance        | ElastiCache cluster (prod-us)     | Env var                    | Use                                  |
| --------------------- | --------------------------------- | -------------------------- | ------------------------------------ |
| Ingestion Redis       | `ingestion-prod-redis`            | `INGESTION_REDIS_HOST`     | Overflow state, pub/sub coordination |
| PostHog/Primary Redis | `posthog-solo`                    | `POSTHOG_REDIS_HOST`       | Billing/quota, restrictions, general |
| Cookieless Redis      | `cookieless-prod-redis`           | `COOKIELESS_REDIS_HOST`    | Cookieless server hash mode          |
| CDP Redis             | `cdp-delivery-prod-redis`         | `CDP_REDIS_HOST`           | CDP Hog function delivery            |
| Dedup Redis           | `ingestion-duplicates-prod-redis` | `DEDUPLICATION_REDIS_HOST` | Event deduplication                  |

Ingestion-side Redis metrics: `overflow_redirect_redis_*`, `cookieless_redis_error`.
Infrastructure-side: CloudWatch datasource `P034F075C744B399F`.

prod-eu uses the same logical cluster names but different endpoint suffixes
(`.mkct36...euc1` instead of `.nfjpjm...use1`).
The prod-eu primary Redis is `posthog-prod-redis-encripted` (sic — the typo is in the actual cluster name).

### Kafka topology

Two backing systems:

- **MSK** — prod-us: `posthog-prod-us-events-2026-03-08` (12 brokers, `kafka.m7g.8xlarge`, tiered storage); prod-eu: `posthog-prod-eu-events-2025-10-16` (15 brokers, `kafka.m7g.4xlarge`)
- **WarpStream** — in-cluster agents in `warpstream-ingestion` namespace; virtual cluster `vcn_ingestion_prod_us` / `vcn_ingestion_prod_eu`

KMinion instance for MSK: `app_kubernetes_io_instance=~"kminion-msk-analytics"`.

### Postgres topology

| DB          | Aurora cluster (prod-us)                                      | Ingestion PgBouncer                                     |
| ----------- | ------------------------------------------------------------- | ------------------------------------------------------- |
| Main app DB | `posthog-cloud-prod-us-east-1` (2x `db.r8g.16xlarge`)         | `ingestion-default-pgbouncer.posthog.svc.cluster.local` |
| Persons DB  | `posthog-cloud-persons-prod-us-east-1` (3x `db.r8g.24xlarge`) | `ingestion-events-pgbouncer.posthog.svc.cluster.local`  |

Postgres metrics via `prometheus-postgres-exporter` and `prometheus-postgres-persons-exporter`.

prod-eu: `posthog-cloud-prod-eu-central-1` and `posthog-cloud-persons-prod-eu-central-1`.

### ClickHouse topology

ClickHouse is the **ultimate downstream consumer** of events the ingestion pipeline produces.
Ingestion workers never talk to CH directly — they publish to Kafka topics which CH
consumes via its built-in Kafka engine and Kafka Connect (DuckLake).
CH health directly impacts perceived ingestion quality: if CH falls behind on consumption,
users see stale data.

**Cluster roles** (discovered via `type` label on `ClickHouseMetrics_*`):

| `type` label      | Role                          | Notes                                      |
| ----------------- | ----------------------------- | ------------------------------------------ |
| `events`          | Main analytics events cluster | Consumes `clickhouse_events_json`          |
| `online`          | Online/fast queries cluster   | Replicated from events                     |
| `offline`         | Offline/batch queries cluster | Replicated from events                     |
| `medium`          | Medium-sized tables           | Persons, groups                            |
| `small`           | Small/config tables           | Infrequent writes                          |
| `sessions`        | Session replay data           | Consumes session recording topics          |
| `logs`            | Logs cluster                  | Consumes logs topics                       |
| `logs-new-schema` | Logs new schema migration     | Migration target                           |
| `ai-events`       | AI/LLM events                 | Consumes AI events topics                  |
| `endpoints`       | API endpoints cluster         | Lightweight                                |
| `migrations`      | Migration-specific            | Schema changes                             |
| `aux` / `ops`     | Auxiliary/operations          | Maintenance                                |
| `batch-exports`   | Batch exports                 | prod-us has this; may not exist in prod-eu |
| `test`            | Testing cluster               | May not exist in all envs                  |

Most `type` label values are identical across prod-us and prod-eu. Minor differences
like `batch-exports` or `test` may exist only in one env.

**Two consumption paths from Kafka to ClickHouse:**

1. **ClickHouse Kafka Engine** — native CH feature. Metrics prefixed `ClickHouseProfileEvents_Kafka*`
   (e.g., `KafkaMessagesPolled`, `KafkaRowsRead`, `KafkaRowsRejected`, `KafkaCommitFailures`).
   Consumer groups: `clickhouse_events_json` (prod-us), `group1` / `group1_recent` (prod-eu).
2. **Kafka Connect** — runs in `kafka-connect` namespace, uses DuckLake sink connector.
   Metrics prefixed `kafka_connect_*` and `kafka_connect_ducklake_sink_task_metrics_*`.
   Consumer groups: `connect-events-ducklake*`.

**Key health signals for ingestion operators:**

- `kminion_kafka_consumer_group_topic_lag{group_id=~"clickhouse_events_json|group1|group1_recent", topic_name="clickhouse_events_json"}` — lag between ingestion output and CH consumption (group name differs by env: `clickhouse_events_json` in prod-us, `group1`/`group1_recent` in prod-eu)
- `kminion_kafka_consumer_group_topic_lag_seconds` with same group filter — same in seconds
- `ClickHouseProfileEvents_KafkaRowsRejected` — rows CH couldn't parse/insert
- `ClickHouseProfileEvents_FailedInsertQuery` — insert failures (schema issues, too many parts, etc.)
- `ClickHouseAsyncMetrics_MaxPartCountForPartition` — rising part count = merge pressure
- `ClickHouseMetrics_ReadonlyReplica` — replicas that fell behind and went read-only
- `ClickHouseAsyncMetrics_ReplicasMaxAbsoluteDelay` — max replication delay
- `posthog_celery_clickhouse_table_parts_count` / `_table_row_count` — Django-side CH health monitors

### Pyroscope services

| Service name                                                | Deployment                   |
| ----------------------------------------------------------- | ---------------------------- |
| `ingestion/ingestion-events`                                | Main analytics               |
| `ingestion/ingestion-events-overflow`                       | Overflow lane                |
| `ingestion/ingestion-events-historical`                     | Historical lane              |
| `ingestion/ingestion-events-async`                          | Async lane                   |
| `ingestion/ingestion-heatmaps`                              | Heatmaps                     |
| `ingestion/ingestion-client-warnings`                       | Client warnings              |
| `ingestion/ingestion-general-turbo`                         | General turbo (prod-us only) |
| `ingestion/ingestion-logs`                                  | Logs ingestion               |
| `ingestion/ingestion-batch-imports`                         | Batch imports                |
| `ingestion-errortracking-main/ingestion-errortracking-main` | Error tracking               |
| `recordings/recordings-blob-ingestion-v2`                   | Session replay               |

Profile types: `process_cpu:cpu:nanoseconds:cpu:nanoseconds`,
`wall:wall:nanoseconds:wall:nanoseconds`,
`memory:inuse_space:bytes:inuse_space:bytes`,
`memory:inuse_objects:count:inuse_space:bytes`.

### Grafana dashboards

| UID                                    | Title                                       | Focus                                         |
| -------------------------------------- | ------------------------------------------- | --------------------------------------------- |
| `ingestion-general`                    | Ingestion - General                         | Cross-service overview, E2E lag, topic flow   |
| `ingestion-pipelines`                  | Ingestion - Pipelines                       | Per-lane pipeline step breakdown              |
| `ingestion-pipeline-performance`       | Ingestion - Pipeline Performance            | Step latency, batch utilization               |
| `ingestion-reliability`                | Ingestion - Reliability                     | Error rates, DLQ, drop causes                 |
| `ingestion-autoscaling`                | Ingestion - Autoscaling                     | HPA/KEDA scaling                              |
| `ingestion-person-processing`          | Ingestion -- Person Processing              | Person store, merge, cache                    |
| `ingestion-group-processing`           | Ingestion -- Group Processing               | Group store                                   |
| `ingestion-session-recordings`         | Session Replay -- Ingestion                 | Replay blob pipeline                          |
| `ingestion-capture`                    | Ingestion - Capture                         | Capture-specific ingestion metrics            |
| `ceef2kuqw66tca`                       | Ingestion copy for warpstream               | WarpStream-specific                           |
| `personhog-service`                    | Personhog service                           | PersonHog latency decomposition               |
| `personhog-cdp-migration`              | PersonHog CDP/NodeJS migration              | PersonHog rollout                             |
| `dbfgkwxs3gw8owd`                      | KMinion Consumer Group Lag                  | Consumer lag by group (including CH groups)   |
| `logs`                                 | Logs (product)                              | Logs ingestion                                |
| `vm-clickhouse-cluster-overview`       | ClickHouse (cluster overview)               | QPS, memory, disk, replication, parts, merges |
| `8aa35a4a-091a-4645-ac8f-ae46901f0060` | ClickHouse Ingestion Layer - Resource Usage | K8s resources for `chi-ingestion-*` pods      |
| `dafd3tvakk4t1cd`                      | ClickHouse - Data Inserted Per Table        | Insert rates per table                        |
| `edvegyvt4u8sge`                       | ClickHouse - Query Metrics                  | Query performance                             |
| `clickhouse-keeper`                    | ClickHouse Keeper                           | ZooKeeper replacement health                  |
| `ef2loyheonm68a`                       | ClickHouse - table sizes and growth         | Storage growth                                |
| `ef7h2todfg4xsd`                       | New ClickHouse Cluster Merge Overview       | Merge throughput                              |
| `cdzv7o1635n9ca`                       | Kafka Connect                               | Kafka Connect tasks, lag, DuckLake sink       |
| `ddpxkllwxg268e`                       | (ingestion vs past)                         | CH ingestion rate vs historical comparison    |
| `deoz13wy08wsga`                       | ClickHouse - Disk capacity (EU ONLY)        | EU-specific disk dashboard                    |

## Discovery workflows

### Prometheus / VictoriaMetrics

1. `list_prometheus_metric_names` — `datasourceUid: "victoriametrics"`, `regex: "ingestion_.*"` to enumerate app metrics
2. Pick a metric, then `list_prometheus_label_names` scoped to it — see available dimensions
3. `list_prometheus_label_values` — discover actual values for a label
   (e.g. `labelName: "cause"` on `ingestion_event_dropped_total`)
4. `query_prometheus` with PromQL — always scope by `app` or `ingestion_pipeline` and set a time range

Repeat with other prefixes: `consumed_batch_*`, `person_*`, `personhog_*`,
`overflow_redirect_*`, `ClickHouseMetrics_*`, `kafka_connect_*`, etc.

### Loki (logs)

1. `list_loki_label_names` — `datasourceUid: "P44D702D3E93867EC"`
2. `list_loki_label_values` for `app` — find ingestion containers (values like `ingestion-events`, `ingestion-logs`, etc.)
3. `query_loki_logs` — e.g. `{app=~"ingestion-.*"} |= "error"` or `{namespace="clickhouse"} |= "Exception"`

### Pyroscope (profiling)

1. `list_pyroscope_profile_types` — `data_source_uid: "pyroscope"`
2. `fetch_pyroscope_profile` — `matchers: '{service_name="ingestion/ingestion-events"}'`,
   `profile_type: "process_cpu:cpu:nanoseconds:cpu:nanoseconds"`

### Dashboards

1. `search_dashboards` — query `"ingestion"` or `"clickhouse"` or a specific deployment name
2. `get_dashboard_by_uid` — use a known UID (e.g. `"ingestion-general"`) to get panel details
3. `get_dashboard_panel_queries` — extract PromQL from existing panels

### Redis / ElastiCache

- Ingestion-side: discover `overflow_redirect_redis_*`, `cookieless_redis_*` metrics in VictoriaMetrics
- Infrastructure: CloudWatch datasource `P034F075C744B399F` for ElastiCache
  (CPU, memory, connections, latency).
  Cluster IDs: `ingestion-prod-redis`, `posthog-solo` (prod-us primary),
  `ingestion-duplicates-prod-redis`, `cookieless-prod-redis`

### Postgres / Aurora

- Ingestion-side: discover `postgres_error_total`, `person_*`, `group_*` metrics
- Infrastructure: `prometheus-postgres-exporter` and `prometheus-postgres-persons-exporter` metrics
- CloudWatch RDS: datasource `P034F075C744B399F` with cluster IDs
  `posthog-cloud-prod-us-east-1` / `posthog-cloud-persons-prod-us-east-1`

### ClickHouse

- Cluster health: `list_prometheus_metric_names` with regex `"ClickHouseMetrics_.*"` or `"ClickHouseProfileEvents_.*"`
  Scope with `type` label for cluster role (e.g. `type="events"`)
- Kafka engine health: regex `"ClickHouseProfileEvents_Kafka.*"`
- Kafka Connect: regex `"kafka_connect_.*"` — scope with `namespace="kafka-connect"`
- Consumer lag (the bridge): `kminion_kafka_consumer_group_topic_lag` with
  `group_id=~"clickhouse_events_json|group1|group1_recent|connect-events-ducklake.*"` and `topic_name="clickhouse_events_json"`
- Logs: `{namespace="clickhouse"} |= "Exception"` or `{namespace="kafka-connect"}`
- Dashboards: `vm-clickhouse-cluster-overview`, `8aa35a4a-091a-4645-ac8f-ae46901f0060`,
  `cdzv7o1635n9ca`

## Key metric domains

Categories of what to look for. Discover specific metrics live using the prefixes above.

**Kafka consumer health** — batch duration, messages consumed per batch, consumer group
assignment/rebalance events, consumer lag (via KMinion). Metrics: `consumed_batch_*`,
`kafka_consumer_*`, `kminion_kafka_consumer_group_topic_lag*` scoped by `group_id`.

**Pipeline processing** — step-level latency and error rates, pipeline result distribution
(ingested, filtered, dropped, DLQ'd). Metrics: `events_pipeline_step_ms`,
`events_pipeline_step_error_total`, `ingestion_pipeline_results` by `result`.

**Person/group stores** — person flush latency, cache hit rates, Postgres write latency,
merge failures, properties size. Metrics: `person_*`, `group_*`, `personhog_*`.

**Outputs** — Kafka production to ClickHouse-bound topics. Message size, latency, errors.
Metrics: `ingestion_outputs_*` by `topic`.

**Overflow routing** — stateful overflow decisions, Redis operations for overflow state.
Metrics: `overflow_redirect_*` by `type`, `result`, `decision`.

**ClickHouse downstream health** — CH cluster QPS, memory, disk, merge pressure,
replication lag, Kafka engine consumption (rows read/rejected/failed), Kafka Connect
task health and consumer lag. This tells you whether events are actually making it
to the query layer. Metrics: `ClickHouseMetrics_*`, `ClickHouseProfileEvents_*`,
`ClickHouseAsyncMetrics_*` scoped by `type`; `kafka_connect_*` scoped by `namespace`.

**K8s resources** — `container_*` and `kube_*` for CPU, memory, restarts, HPA state.
Scope: `namespace="posthog"`, `pod=~"ingestion-.*"` (or `namespace="clickhouse"`,
`pod=~"chi-ingestion-.*"` for CH ingestion pods).

## Investigation playbooks

See [references/investigation-playbooks.md](./references/investigation-playbooks.md)
for step-by-step workflows covering: health checks, event drops, latency, consumer lag,
person processing, Kafka/MSK issues, Redis, Postgres, session replay, ClickHouse
downstream health, and cross-environment comparison.
