# Metrics: the events model (`metric_events`) — architecture & decisions

Companion to [`deployment-layout.md`](./deployment-layout.md), [`dashboard-mvp.md`](./dashboard-mvp.md), and [`dev-bridge-fixes.md`](./dev-bridge-fixes.md).

**Status:** the foundation stack is open as drafts — [#66163](https://github.com/PostHog/posthog/pull/66163) (table), [#66169](https://github.com/PostHog/posthog/pull/66169) (HogQL), [#66183](https://github.com/PostHog/posthog/pull/66183) (ingest).
The read/product layer (query runner, Samples view, trace pivot, frontend) comes next, **extending the existing metrics product** rather than standing up a separate surface.

## The differentiating line (read this first)

PostHog now has **two** metrics storage models, both on the LOGS ClickHouse cluster, both fed from the **same** Kafka stream:

|                              | `metrics1` (pre-aggregated TSDB)                                                                                         | `metric_events` (events model)                                                 |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| **Row granularity**          | rolled up per `(team, time_bucket, service, metric, resource_fingerprint)` with a counts/min/max projection              | **one row per emission**                                                       |
| **When aggregation happens** | at write / projection time                                                                                               | **at query time**                                                              |
| **Carries**                  | `count`, `histogram_bounds`/`histogram_counts`, `aggregation_temporality`, `is_monotonic`, `projection_aggregate_counts` | `value`, `kind`, **`trace_id` (bloom-indexed)**, high-cardinality `attributes` |
| **`ORDER BY`**               | `(team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)`                                     | `(team_id, metric_name, timestamp)`                                            |
| **Cardinality posture**      | bounded (rolls up)                                                                                                       | unbounded (every point) → needs TTL + quota                                    |
| **Retention**                | none today                                                                                                               | **30 days**                                                                    |
| **Query shapes**             | `rate` / `increase` / `histogram_quantile` time-series                                                                   | **samples list, query-time agg, trace pivot**                                  |
| **Best for**                 | dashboards, alerts — "is it up, how fast, what's the trend"                                                              | debugging a spike — "show me the actual events, and the trace behind this one" |
| **Sentry analog**            | the model they moved _away_ from for the detail view                                                                     | "Samples" / Trace — the model they moved _to_                                  |

**One sentence:** `metrics1` answers _"what is the shape of this metric over time"_; `metric_events` answers _"what were the individual emissions, and what trace caused this one."_

They are **complementary, not a migration.** Neither replaces the other. A dashboard tile stays on `metrics1`; clicking into a spike to see the underlying events and jump to a trace is `metric_events`.

## Why two models (the Sentry pivot)

Sentry shipped pre-aggregated metrics, then publicly pivoted away from them (they wrote up the mistake on the Sentry engineering blog): pre-aggregation throws away exactly the information you need when something breaks.
You can see _that_ p99 latency spiked, but not _which_ requests, with _which_ tags, tied to _which_ traces.
Their fix was to store metric emissions as **events** with full attributes and trace linkage, and aggregate at read time — trading storage and query cost for the ability to drill from a chart all the way to a single trace.

PostHog already has the platform that makes this cheap to adopt: an events/observability pipeline (capture-logs → Kafka → ClickHouse on the LOGS cluster) that already carries logs and traces with `trace_id`.
Putting metric emissions next to them on the same cluster makes the metric→trace pivot a same-cluster lookup, not a cross-system join.
`metrics1` stays as the efficient TSDB for dashboards and alerts; `metric_events` adds the differentiated drill-down.

## Architecture

### The pipeline (shared all the way to ClickHouse)

```text
SDK / OTLP / Prometheus remote-write
        │
        ▼
   capture-logs (Rust gateway)         maps everything to one Avro MetricRecord
        │  produces → topic: ingestion-metrics  (warpstream-metrics)
        ▼
   metrics-ingestion (Node consumer)   transform / enrich
        │  produces → topic: clickhouse_metrics
        ▼
   ClickHouse LOGS cluster
        │
        ▼
   kafka_metrics_avro   (Kafka engine, Avro, group clickhouse-metrics-avro[-new])
        │
        ├── kafka_metrics_avro_mv ─────────────▶ metrics1        (pre-aggregated TSDB)   ← existing
        │
        └── kafka_metrics_avro_to_metric_events ▶ metric_events  (events model)          ← NEW (#66183)
```

The key move: **one Kafka consumer, two destinations.**
ClickHouse delivers every message from a Kafka-engine table to _all_ attached materialized views, so adding a second MV fans each data point into both tables.
No new topic, consumer group, named collection, or Rust change — the existing `MetricRecord` Avro is already a superset of what the events model needs (it carries `value`, `trace_id`/`span_id`/`trace_flags`, `metric_type`, and the attribute maps).

### Where things live

- **Storage:** `metric_events1` (base, `ReplicatedMergeTree` in prod / `MergeTree` locally) + `metric_events` (Distributed wrapper) on the LOGS cluster, database `CLICKHOUSE_LOGS_CLUSTER_DATABASE`.
- **Table definition:** `posthog/clickhouse/metrics/metric_events.py`, registered in `posthog/clickhouse/schema.py`, created in prod by migration `0277_metric_events.py` (`node_roles=[NodeRole.LOGS]`).
- **Ingest (Kafka table + MVs):** `bin/clickhouse-metrics.sql`. Deliberately **not** in migrations — see D2 below.
- **Query exposure:** `MetricEventsTable` in `posthog/hogql/database/schema/metrics.py`, registered in `posthog/hogql/database/database.py` under the `posthog` namespace → queryable as `posthog.metric_events`.

### Query exposure (HogQL)

`metric_events` is reachable as `posthog.metric_events`, with `team_id` isolation enforced by the HogQL layer (every compiled query gets a `team_id` filter injected — verified, not assumed).
The events-model aggregations map by `kind`:

- `counter` → `count()` / `sum(value)`
- `gauge` → `argMax(value, timestamp)`
- `distribution` → `quantile(value)` (raw values, no pre-bucketed histogram)

The trace pivot is a `trace_id` equality lookup, served by the `idx_trace_id_bf` bloom filter.

## Decisions & alternatives

### D1 — Dual-write via a second MV, not a new topic/consumer

**Context:** `metric_events` needs to be populated from the metric stream.
**Decision:** attach a second MV (`kafka_metrics_avro_to_metric_events`) to the existing `kafka_metrics_avro` Kafka table.
**Alternatives rejected:**

- _New capture-logs topic + producer_ — Rust changes, a new WarpStream cluster/topic, new consumer group; weeks of infra for no extra capability.
- _New Kafka-engine table on the same topic with its own consumer group_ — doubles Kafka fetch load and lets the two tables drift out of sync on rebalance.

**Consequence:** zero new infrastructure, and `metrics1` and `metric_events` are guaranteed to see the exact same data because they read from one consumer. Cost: the new MV shares the source table's fate — a malformed-row bug in its `SELECT` could stall consumption for both, so the mapping mirrors the proven `metrics1` MV (`ifNull` guards, `kafka_skip_broken_messages = 100`).

### D2 — Ingest DDL stays hand-managed, not in migrations

**Context:** Django/ClickHouse migrations are the norm for storage tables.
**Decision:** the Kafka-engine table and the Kafka→storage MVs live in `bin/clickhouse-metrics.sql` + manual prod DDL (recorded in the PR), matching how `metrics1`/`kafka_metrics_avro` are already deployed. The **storage** table (`metric_events1`) does get a real migration.
**Why:** the Avro Kafka tables reference environment-specific brokers/named-collections and are intentionally kept out of `schema.py` (the logs Kafka tables aren't there either). Forcing the MV into a migration would make it depend on `kafka_metrics_avro`, which no migration creates — it would fail on a fresh cluster.
**Consequence:** consistent with the existing metrics pipeline, but the prod MV is a manual step on merge (see Operational notes). This is a known rough edge of the metrics product, not new debt introduced here.

### D3 — 30-day TTL on `metric_events`

**Context:** `metrics1` has no retention today; events are far higher volume.
**Decision:** `TTL toDateTime(timestamp) + INTERVAL 30 DAY`, `ttl_only_drop_parts = 1`.
**Why:** one-row-per-emission is unbounded; without a TTL the table grows without limit. 30 days covers the debugging window (you drill into a spike while it's recent) while bounding cost. `ttl_only_drop_parts` makes expiry a cheap partition drop, not a mutation.

### D4 — `trace_id` is a first-class, bloom-indexed column

**Context:** the whole point of the events model is the metric→trace pivot.
**Decision:** keep `trace_id`/`span_id`/`trace_flags` as real columns and add `idx_trace_id_bf` (bloom filter) plus bloom indexes on attribute keys and values.
**Why:** the pivot ("show me the trace behind this emission") and high-cardinality attribute filters are the queries that justify the events model existing; they must be cheap.

### D5 — Reuse the metrics Avro stream; no SDK or Rust changes for v1

**Context:** we could define a new PostHog-native metric-event wire format.
**Decision:** populate `metric_events` from the existing `clickhouse_metrics` Avro stream.
**Consequence:** instant dogfooding on everything already emitting metrics, with no client work. The one limitation this imposes is D-known below.

## What's built (the stack)

| PR                                                      | Branch                              | Scope                                                                        |
| ------------------------------------------------------- | ----------------------------------- | ---------------------------------------------------------------------------- |
| [#66163](https://github.com/PostHog/posthog/pull/66163) | `posthog-code/metric-events-table`  | `metric_events1` + distributed table, migration `0277`, `schema.py`, 30d TTL |
| [#66169](https://github.com/PostHog/posthog/pull/66169) | `posthog-code/metric-events-hogql`  | `MetricEventsTable` → `posthog.metric_events` in HogQL                       |
| [#66183](https://github.com/PostHog/posthog/pull/66183) | `posthog-code/metric-events-ingest` | second MV on `kafka_metrics_avro` → dual-write `metric_events`               |

Each was validated against local ClickHouse before commit (the four events-model query shapes; HogQL compile with `team_id` injection; the MV type-checking against the real Avro source). Two bugs were caught by those gates pre-commit (CH multi-statement rejection; a pydantic `description` annotation).

## What's next (read/product layer)

Built **into the existing metrics product** (new capability alongside the `metrics1` time-series UI), each step locally validatable with inserted rows:

1. **Query-time aggregation runner** for the events model (`counter`/`gauge`/`distribution`) — distinct from the `metrics1` `MetricQueryRunner`, which is built for the pre-aggregated/histogram-bucket shape.
2. **Samples endpoint** — list raw emissions with their attributes (the Sentry "Samples" tab).
3. **Trace pivot** — the metric→trace jump, the feature that justifies the model.
4. **SDK emit** for raw distribution samples (closes the D-known limitation).
5. **Frontend** — Samples tab + trace links in the existing metrics scene.
6. **Cardinality / volume quota** — guard the unbounded write path per team.

## Operational notes

### Prod DDL to apply on merge

`metric_events1` ships via migration `0277`. The **ingest MV is a manual step** on both LOGS regions (it depends on the prod `kafka_metrics_avro`). The exact `ReplicatedMergeTree`-flavored statement is in the [#66183](https://github.com/PostHog/posthog/pull/66183) body; mirror it into the metrics handoff/runbook when applying.

### Cardinality & cost

The events model writes one row per emission with high-cardinality attributes — the cost trade for query-time flexibility.
The 30-day TTL bounds it; a per-team volume quota (item 6 above) is the planned backstop before opening it to customer ingest.
Watch the same consumer-lag signal as `metrics1` (`metrics_kafka_metrics`) — the new MV rides the same Kafka table, so its write amplification shows up there.

### Known limitation — pre-bucketed distributions

Because v1 reuses the OTLP/Prometheus stream (D5), histogram/distribution metrics arrive **already bucketed**.
A distribution therefore lands as a single `metric_events` row carrying its `value`, not as raw samples.
Counters and gauges are true one-row-per-emission today; raw distribution samples need the SDK emit path (next-layer item 4).
Quantiles over distributions are exact only once that lands; until then they reflect the bucketed input.
