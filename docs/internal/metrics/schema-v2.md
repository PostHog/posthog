# Metrics schema v2 — series + samples layout
> Provenance convention used throughout: **[RORY-PROD]** = copied verbatim from the production-tested managed schemas in `posthog-cloud-infra/ansible/roles/clickhouse/templates/managed_schemas/8*.posthog.metrics_*.sql.j2` (live on the ops clusters) or Snuffle source at commit `ab5156c`. **[ADAPTED]** = changed for the logs cluster / multi-tenant product context. **[INFERRED]** = our design, no Rory reference — needs his review.
## 1. Goals

1. **~10x disk reduction at scale.** `metrics1` carries `resource_attributes` + `attributes_map_str`/`_float` maps on every sample row; a metric sample is otherwise just a float, so the maps dominate (~100x the payload of the value — Rory, Jun 4). His Snuffle benchmark: **3.28 bytes/sample (series+samples) vs 31.25 bytes/sample (metrics1 shape)** — 89.5% less disk. Labels move to a per-series dictionary written once; samples become fixed-width `(team_id, metric_name, timestamp, id, value)` rows.
2. **PromQL-native reads.** The new tables are exactly what Snuffle's `current` layout expects, so the real Prometheus engine (via Snuffle) serves `/api/v1/query{,_range}` over customer metrics with its fast paths (label-index pruning, `timeSeries*ToGrid` pushdown) instead of the per-row `xxHash64(mapSort(...))` series-identity tax the `posthog` layout pays.
3. **Working `histogram_quantile`.** Snuffle never reads `metrics1.histogram_bounds/histogram_counts` (confirmed by grep — zero references), so OTLP-native histograms are invisible to PromQL today. v2 explodes histograms into classic per-`le` `_bucket`/`_sum`/`_count` series at ingest, which both Snuffle and the PostHog QL layer can quantile over.
4. **Keep the #956 philosophy: raw samples + TTL, no rollups.** This is a *row-layout* change, not a revisit of the merged RFC decision. Every sample is still stored raw; retention is still TTL-by-age. The 5–10x cost challenge was always about layout, not about pre-aggregation.
5. **team_id multi-tenancy on every table.** Every table leads its ORDER BY with `team_id` and every read includes the tenant filter (Snuffle already does this; the PostHog QL layer does it via HogQL team scoping).

## 2. Non-goals

- **Rollups / resolution decay.** Explicitly rejected by RFC #956; Andy Zhao's hybrid-rollup question stays open and is unaffected by this rewrite.
- **PromQL reimplementation.** Snuffle (real Prometheus engine) is the PromQL plane; the prom-compat Go service (#61302/#61315) stays parked/recommended-close.
- **Changing the producer (capture-logs) or the OTLP contract.** `/i/v1/metrics`, the Avro schema on `ingestion-metrics`/`clickhouse_metrics`, and `metric_record.rs` are untouched in v1 of this rewrite (see §5 for why).
- **Changing the QL-track wire shape or facade contracts.** `[MetricSeries]`, `attribute_field()`, filters/group-by/rate land against `metrics1` per the scope plan; this track only swaps what's underneath the seam.
- **Delta→cumulative conversion at ingest.** Stateful temporality conversion is out of scope for v1; see open question Q4.
- **Backfill of historical `metrics1` data.** See §8.5.
- **Naming translation.** Keep-as-emitted (checkpoint-1 decision #4). The only derived names are the standard Prometheus histogram/summary expansions (`_bucket`/`_sum`/`_count`, `quantile` label), which match what Prometheus-ecosystem users already see.

## 3. Reference: the Snuffle `current` layout

Six tables + one MV, production-tested on the ops ClickHouse clusters (prod-us, prod-eu) where Snuffle serves the internal vmagent remote-write store. Two further tables (`metrics_label_postings`, `metrics_series_activity`) exist in Snuffle's config surface and DROP lists but their managed-schema templates are **empty** — they are vestigial/abandoned in prod; we do not adopt them (open question Q2).

| table | role | engine (prod) | ORDER BY |
|---|---|---|---|
| `metrics_series` | series dictionary: id → labels_json (one row per series; `__name__` excluded from the JSON, held in `metric_name`) | ReplicatedMergeTree | `(team_id, metric_name, id)` + projection `by_id` ordered `(team_id, id)` |
| `metrics_samples` | float samples, fixed-width | ReplicatedMergeTree, PARTITION BY toYYYYMMDD | `(team_id, metric_name, id, timestamp)` |
| `metrics_label_index` | inverted index: (label_name, label_value) → id | ReplicatedReplacingMergeTree + projections `by_label_value`, `by_id_label` | `(team_id, metric_name, label_name, label_value, id)` |
| `metrics_histograms` | Prometheus **native** histograms as prompb protobuf blobs | ReplicatedReplacingMergeTree(version) | `(team_id, id, timestamp)` |
| `metrics_exemplars` | exemplars: id + value + labels_json | ReplicatedMergeTree | `(team_id, id, timestamp)` |
| `metrics_metadata` | metric family → type/unit/help | ReplicatedReplacingMergeTree(updated_at) | `(team_id, metric_family_name)` |
| `metrics_label_index_from_series_mv` | MV: series insert → ARRAY JOIN of labels_json → label_index | — | — |

Key mechanics (from Snuffle source, `remote.go`/`storage.go`/`fastpath.go`):

- **Series id** = xxhash64 over the sorted label set, encoded as `len(name) LE-u64 ‖ name ‖ len(value) LE-u64 ‖ value` per label, **including `__name__`** (`remoteWriteSeriesIdentityLabels`). The id is team-independent (team_id is a column, not part of the hash).
- **Write path (Snuffle remote-write):** per batch it inserts only series ids not already present for the team (`SELECT id ... NOT IN (SELECT id FROM metrics_series WHERE team_id = N)` with an external-table id list), then samples/histograms/exemplars/metadata unconditionally. `metrics_label_index` is populated purely by the MV off series inserts — nothing writes it directly.
- **Read path tolerates duplicate series rows.** Every series selection wraps in `GROUP BY id` with `any(labels_json)` / `min(min_time)` / `max(max_time)` aggregates (`selectSeriesMatching`, `selectedSeriesSQL`). This is load-bearing for our ingestion design (§5): at-least-once Kafka delivery into `metrics_series` is read-correct; dedup is a disk concern only.
- **Label matchers** become `id IN/NOT IN (SELECT id FROM metrics_label_index WHERE team_id = N AND label_name = 'k' AND <condition>)` membership filters (`seriesPreFilters`), riding the `by_label_value` projection; `__name__` matchers hit `metric_name` directly. Exact semantics are always re-verified Go-side.
- **Series time-pruning:** with an exact metric name, active ids come from the samples table itself; otherwise it falls back to `max_time >= mint AND min_time <= maxt` on the series rows. Snuffle never updates min/max after first insert, so that fallback goes stale — our periodic re-emission (§5.3) actually improves on this.
- **labels_json is never JSONExtract'd in the sample hot path** — only over the (small) selected series set. Keep that property in the PostHog QL implementation too.
- **Hard requirement:** range-query fast paths use `timeSeriesLastToGrid` / `timeSeries*RateToGrid` with `allow_experimental_time_series_aggregate_functions=1` → ClickHouse ≥ 25.6. The logs clusters and local dev (26.3.10.60) qualify.

## 4. Proposed DDL — PostHog variant on the logs cluster

Conventions, matching how `metrics1` was applied (Bryan's dev SQL → METRICS-PROD-APPLY.md):

- database `posthog`, `ON CLUSTER logs` (manual `clickhouse-client` apply — the "no ON CLUSTER" rule in `posthog/clickhouse/migrations/README.md` applies only to the Django events-cluster framework);
- ReplicatedMergeTree ZK paths `/clickhouse/tables/logs/{shard}/posthog.<table>` **[ADAPTED — this is the dev-cluster convention; per Bryan's #11702 caveat, verify prod ZK path conventions against the live `metrics1` engine string before the prod apply and substitute (runbook step, §8.4)]**;
- Distributed read aliases over cluster `logs` for app-side (HogQL) reads. Inner table names are kept **identical to Snuffle's defaults** so a colocated Snuffle in `current` layout works with zero table-name env overrides; Distributed wrappers get a `_dist` suffix **[INFERRED — naming; the existing pair is `metrics1`/`metrics`, but `metrics_samples` is already the canonical inner name in Rory's layout, so the suffix goes on the wrapper instead]**;
- no column-level compression codecs (Rory's standing review note from the metrics1 review: "remove the column level compression codecs and leave the defaults"). Note the OSS Snuffle script *does* carry `DoubleDelta`/`Gorilla` codecs; the prod managed schemas do not. We follow prod. **[RORY-PROD]**
- `team_id UInt64` to stay byte-compatible with Rory's DDL and Snuffle's tenant handling (uint64), even though `metrics1` uses `Int32`. PostHog team ids are positive integers; conversion at write time is lossless.

Divergences from [RORY-PROD] are flagged inline. Everything else is a verbatim copy with the engine path/cluster adapted.

### 4.1 `metrics_series`

```sql
CREATE TABLE IF NOT EXISTS posthog.metrics_series ON CLUSTER logs
(
    `team_id` UInt64,
    `id` UInt64,
    `metric_name` LowCardinality(String),
    `labels_json` String,
    `min_time` DateTime64(3, 'UTC'),
    `max_time` DateTime64(3, 'UTC'),
    PROJECTION by_id
    (
        SELECT team_id, id, metric_name, labels_json, min_time, max_time
        ORDER BY (team_id, id)
    )
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/logs/{shard}/posthog.metrics_series', '{replica}', max_time)
ORDER BY (team_id, metric_name, id)
TTL toDateTime(max_time) + INTERVAL 30 DAY
SETTINGS index_granularity = 1024, deduplicate_merge_projection_mode = 'rebuild', ttl_only_drop_parts = 0;
```

**[ADAPTED, two divergences from RORY-PROD — both need Rory's sign-off (Q2, Q3):**

1. **Engine: ReplacingMergeTree(max_time) instead of plain MergeTree.** Rory's writer (Snuffle remote-write) does a read-before-write existence check, so plain MergeTree never accumulates duplicates. Our writer is Kafka (at-least-once, no existence check, plus deliberate periodic re-emission — §5.3), so duplicates are structural. Reads are duplicate-safe either way (`GROUP BY id`); Replacing keeps disk bounded and makes the freshest `max_time` win at merge time, which *fixes* the stale-`max_time` series-pruning fallback noted in §3. `deduplicate_merge_projection_mode = 'rebuild'` is required for Replacing+projection (Rory already uses it on `metrics_label_index`).
2. **TTL on max_time.** Rory's table has no TTL (internal ops store, ~bounded cardinality). A multi-tenant customer table needs series garbage collection; because active series are re-emitted at least every `SERIES_REEMIT_INTERVAL` (§5.3), `max_time`-based TTL expires only genuinely dead series. `ttl_only_drop_parts = 0` because series rows for one partition-less table age out row-wise.**]**

### 4.2 `metrics_label_index`

```sql
CREATE TABLE IF NOT EXISTS posthog.metrics_label_index ON CLUSTER logs
(
    `team_id` UInt64,
    `metric_name` LowCardinality(String),
    `label_name` LowCardinality(String),
    `label_value` String,
    `id` UInt64,
    PROJECTION by_label_value
    (
        SELECT team_id, metric_name, label_name, label_value, id
        ORDER BY (team_id, label_name, label_value, id, metric_name)
    ),
    PROJECTION by_id_label
    (
        SELECT team_id, metric_name, label_name, label_value, id
        ORDER BY (team_id, id, label_name, metric_name, label_value)
    )
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/logs/{shard}/posthog.metrics_label_index', '{replica}')
ORDER BY (team_id, metric_name, label_name, label_value, id)
SETTINGS index_granularity = 1024, deduplicate_merge_projection_mode = 'rebuild';
```

**[RORY-PROD verbatim** (incl. `label_value String`, not LowCardinality — the OSS script says LC but prod says String; follow prod) **except the engine path.** No TTL here: rows are tiny and fully deduplicated by Replacing; expired-series index rows are harmless (membership subqueries intersect with live samples). Revisit if it ever dominates — Q3.**]**

### 4.3 `metrics_samples`

```sql
CREATE TABLE IF NOT EXISTS posthog.metrics_samples ON CLUSTER logs
(
    `team_id` UInt64,
    `metric_name` LowCardinality(String),
    `timestamp` DateTime64(3, 'UTC'),
    `id` UInt64,
    `value` Float64
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.metrics_samples', '{replica}')
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, metric_name, id, timestamp)
TTL toDateTime(timestamp) + INTERVAL 30 DAY
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1;
```

**[RORY-PROD verbatim except engine path and the TTL [ADAPTED]** — 30-day default per RFC #956; daily partitions + `ttl_only_drop_parts = 1` makes expiry a cheap part drop. Enterprise 90-day retention is a later per-team TTL story, same as metrics1's plan.**]**

Note the deliberate losses vs `metrics1`, all intentional: no `uuid` (Rory: drop it), no per-row attribute maps (the whole point), timestamp precision µs→ms (DateTime64(3) — Prometheus operates in ms), no `observed_timestamp` (lag tracking stays on the Kafka-side MV, §4.8).

### 4.4 `metrics_histograms`

```sql
CREATE TABLE IF NOT EXISTS posthog.metrics_histograms ON CLUSTER logs
(
    `team_id` UInt64,
    `metric_name` LowCardinality(String),
    `timestamp` DateTime64(3, 'UTC'),
    `id` UInt64,
    `histogram` String,
    `version` UInt64
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/logs/{shard}/posthog.metrics_histograms', '{replica}', version)
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, id, timestamp)
TTL toDateTime(timestamp) + INTERVAL 30 DAY
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1;
```

**[RORY-PROD verbatim except engine path + TTL.]** Created for forward-compatibility but **not written in v1**: the `histogram` column is a serialized `prompb.Histogram` (Prometheus *native* histogram), which is what Snuffle remote-write stores. Our OTel explicit-bounds histograms are instead exploded into classic per-`le` series (§5.4) — that is what makes `histogram_quantile` work in both Snuffle and PostHog QL. Creating the table now means a future native-histogram path (or OTel expo-histogram → native conversion) needs no DDL change, and keeps the schema identical to Rory's. (Q5.)

### 4.5 `metrics_exemplars`

```sql
CREATE TABLE IF NOT EXISTS posthog.metrics_exemplars ON CLUSTER logs
(
    `team_id` UInt64,
    `timestamp` DateTime64(3, 'UTC'),
    `id` UInt64,
    `value` Float64,
    `labels_json` String
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.metrics_exemplars', '{replica}')
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, id, timestamp)
TTL toDateTime(timestamp) + INTERVAL 30 DAY
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1;
```

**[RORY-PROD verbatim except engine path + TTL.]** Where trace correlation goes: OTel exemplar `trace_id`/`span_id` (today reduced to two columns on every metrics1 row, mostly empty) become exemplar rows with `labels_json = {"trace_id": "...", "span_id": "..."}` — the standard Prometheus exemplar-label convention, served by Snuffle's `/api/v1/query_exemplars` and joinable to `trace_spans`/`logs` by the same ids. `id` is the series id of the sample the exemplar annotates (for exploded histograms: the `_bucket` series whose `le` bucket the exemplar's value falls in **[INFERRED — Prometheus convention; v1 may simplify to the `_sum` series, flag in implementation PR]**). Encoding: hex (lowercase, OTel/W3C trace-context style) rather than metrics1's base64 **[INFERRED — base64 in metrics1 was inherited from the logs row shape; hex is what trace tooling expects. Decide once in SR-3 and document]**.

### 4.6 `metrics_metadata`

```sql
CREATE TABLE IF NOT EXISTS posthog.metrics_metadata ON CLUSTER logs
(
    `team_id` UInt64,
    `metric_family_name` LowCardinality(String),
    `type` LowCardinality(String),
    `unit` String,
    `help` String,
    `aggregation_temporality` LowCardinality(String) DEFAULT '',
    `is_monotonic` Bool DEFAULT false,
    `updated_at` DateTime64(3, 'UTC')
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/logs/{shard}/posthog.metrics_metadata', '{replica}', updated_at)
ORDER BY (team_id, metric_family_name)
SETTINGS index_granularity = 1024;
```

**[RORY-PROD + two additive columns [ADAPTED]:** `aggregation_temporality` and `is_monotonic` have no home in the pure Snuffle layout but are load-bearing for QL-5 (temporality-aware `rate`) and currently live per-row in `metrics1`. They are per-metric-family facts, so metadata is the right (and ~free) place. Snuffle selects explicit columns only, so the extra columns are invisible to it — verified against `insertRemoteMetadataRows`/metadata reads. (Q4 covers what to *do* with delta temporality.)**]** `type` values follow Snuffle's `remoteMetadataType` vocabulary (`counter`/`gauge`/`histogram`/`summary`/`unknown`...); the consumer maps OTel `sum` → `counter` when `is_monotonic`, else `gauge` semantics with `type='gauge'` **[INFERRED mapping — document in SR-3]**. `metrics1.metric_type` raw OTel strings remain available during the transition for parity checks.

### 4.7 Label-index MV + Distributed aliases

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS posthog.metrics_label_index_from_series_mv ON CLUSTER logs
TO posthog.metrics_label_index
AS SELECT
    team_id,
    metric_name,
    tupleElement(label_pair, 1) AS label_name,
    tupleElement(label_pair, 2) AS label_value,
    id
FROM posthog.metrics_series
ARRAY JOIN JSONExtractKeysAndValues(labels_json, 'String') AS label_pair;
```

**[RORY-PROD verbatim.]** This is why the ingestion path (§5) never writes `metrics_label_index` directly — series inserts fan out automatically, and Replacing dedup absorbs re-emissions.

```sql
CREATE TABLE IF NOT EXISTS posthog.metrics_series_dist  ON CLUSTER logs AS posthog.metrics_series      ENGINE = Distributed('logs', 'posthog', 'metrics_series');
CREATE TABLE IF NOT EXISTS posthog.metrics_samples_dist ON CLUSTER logs AS posthog.metrics_samples     ENGINE = Distributed('logs', 'posthog', 'metrics_samples');
CREATE TABLE IF NOT EXISTS posthog.metrics_label_index_dist ON CLUSTER logs AS posthog.metrics_label_index ENGINE = Distributed('logs', 'posthog', 'metrics_label_index');
CREATE TABLE IF NOT EXISTS posthog.metrics_histograms_dist ON CLUSTER logs AS posthog.metrics_histograms ENGINE = Distributed('logs', 'posthog', 'metrics_histograms');
CREATE TABLE IF NOT EXISTS posthog.metrics_exemplars_dist ON CLUSTER logs AS posthog.metrics_exemplars  ENGINE = Distributed('logs', 'posthog', 'metrics_exemplars');
CREATE TABLE IF NOT EXISTS posthog.metrics_metadata_dist ON CLUSTER logs AS posthog.metrics_metadata   ENGINE = Distributed('logs', 'posthog', 'metrics_metadata');
```

**[ADAPTED.]** App-side (HogQL) reads go through `_dist`; Snuffle runs colocated on the CH nodes and reads the local inner tables (its ops deployment already does exactly this), so it gets the default table names with no overrides. The logs cluster is single-shard today, so Distributed is a thin convenience layer, same as `metrics` over `metrics1`.

### 4.8 Kafka ingestion tables (new pre-shaped topics)

Four new WarpStream topics (terraform, mirroring `clickhouse_metrics`): `clickhouse_metrics_samples` (high volume — same partition count as `clickhouse_metrics`, 72), `clickhouse_metrics_series`, `clickhouse_metrics_exemplars`, `clickhouse_metrics_metadata` (low volume — fewer partitions fine, e.g. 12). **[INFERRED topic naming/partitioning — follow Jon's #8321 conventions.]**

```sql
-- samples (shown; series/exemplars/metadata follow the same pattern, columns matching §4.1/4.5/4.6)
CREATE TABLE IF NOT EXISTS posthog.kafka_metrics_samples_avro ON CLUSTER logs
(
    `team_id` UInt64,
    `metric_name` String,
    `timestamp` DateTime64(3),
    `id` Int64,                 -- Avro long; reinterpreted to UInt64 in the MV
    `value` Float64
)
ENGINE = Kafka(warpstream_metrics)   -- local dev: Kafka('kafka:9092', ...)
SETTINGS
    kafka_topic_list = 'clickhouse_metrics_samples',
    kafka_group_name = 'clickhouse-metrics-samples-avro',
    kafka_format = 'Avro',
    kafka_skip_broken_messages = 100,
    kafka_thread_per_consumer = 1,
    kafka_num_consumers = 8;

CREATE MATERIALIZED VIEW IF NOT EXISTS posthog.kafka_metrics_samples_mv ON CLUSTER logs
TO posthog.metrics_samples
AS SELECT
    team_id,
    metric_name,
    timestamp,
    reinterpretAsUInt64(reinterpretAsFixedString(id)) AS id,
    value
FROM posthog.kafka_metrics_samples_avro;
```

**[INFERRED — new.** Deliberately *thin*: all shaping (series identity, label JSON, histogram explosion) happens in the Node consumer; the CH-side MVs are passthroughs, unlike the JSON-mangling `kafka_metrics_avro_mv`. That keeps the failure-prone logic testable in TypeScript and the Kafka-engine SQL trivial — directly responding to the prod consumer fragility we just lived through. The `reinterpret` dance is the standard Avro-signed-long → UInt64 round-trip; the producer writes the id's two's-complement long. Add a `metrics_kafka_metrics`-style lag MV for `kafka_metrics_samples_avro` (same pattern as today's `kafka_metrics_avro_kafka_metrics_mv`) so consumer-lag alerting carries over.**]**

The series Kafka MV maps `(team_id, id, metric_name, labels_json, min_time, max_time)` 1:1; exemplars and metadata likewise.

### 4.9 Local dev DDL

`bin/clickhouse-metrics-v2.sql`, sourced by `bin/clickhouse-metrics-init`: same tables without `ON CLUSTER`/replication (plain MergeTree / ReplacingMergeTree), Kafka engine pointed at `kafka:9092`, plus the Distributed aliases over cluster `posthog` to mirror prod read paths — exactly the `metrics1` local pattern. Python builder defs go in `posthog/clickhouse/metrics/` next to `metrics1.py` (`metrics_series.py`, `metrics_samples.py`, …) as the committed source of truth, with the same "not wired to auto-apply" caveat as everything on the logs cluster.

## 5. Ingestion write path

### 5.1 Options considered

**(a) ClickHouse-side MVs off the existing `kafka_metrics_avro` table.** One Kafka table can feed multiple MVs, so in principle: an MV to `metrics_samples` computing the series id, an MV to `metrics_series` building `labels_json`, an MV exploding histograms. Rejected, agreeing with Rory's caveat ("a simple MV from the OTel table probably won't work — separate histogram/metadata tables"). Concretely:
  - The series id must be a stable hash over the *merged, sorted* label set (resource attrs + datapoint attrs + `service_name` + `__name__`). Reproducing Snuffle's length-prefixed xxhash64 in SQL is possible but brutally fragile, and any drift between the SQL implementation and any other writer permanently splinters series.
  - Histogram explosion (bounds/counts arrays → cumulative per-`le` rows, *each with a different series id* because `le` joins the label set) means computing N ids per row inside an `ARRAY JOIN` — compounding the above.
  - Every series row would be emitted per *sample* (MVs are stateless), so the insert volume of `labels_json` would equal today's per-row map volume; Replacing merges would eventually reclaim disk but write amplification and pre-merge read cost stay metrics1-sized.
  - The Kafka→MV path is exactly the component that has been falling over in prod (Frank's "round 2", Jun 11). Stacking five more nontrivial MVs onto the same Kafka table multiplies the blast radius and is undebuggable compared to consumer code.

**(b) Consumer-side shaping in `metrics-ingestion` (Node.js) → new pre-shaped topics → thin Kafka MVs. CHOSEN.** The consumer already sits between `ingestion-metrics` and `clickhouse_metrics`, already resolves token→team and applies quota/rate-limiting, and the workspace already ships `avsc` with an established Avro codec pattern (`logs-ingestion/log-record-avro.ts`). It is the only place in the pipeline that is stateful, horizontally scaled, and written in a language we can unit-test the hashing/explosion logic in. Producing to Kafka (rather than inserting into CH directly) keeps WarpStream durability/replay/lag-tracking and avoids giving consumers CH credentials or a new failure domain.

**(c) capture-logs (Rust) producing a second pre-shaped topic.** Rejected: capture-logs only knows the token (team resolution happens in the Node consumer), so it cannot write `team_id`-keyed rows; pre-shaped rows produced before the consumer would bypass quota and rate-limit drops (billing integrity); and it puts new per-request fan-out logic on the stateless hot capture path with the worst review/rollback story.

### 5.2 Consumer changes (SR-3)

In `MetricsIngestionConsumer.produceValidMetricMessages` (after quota + rate-limit filtering, alongside the untouched pass-through to `clickhouse_metrics`), gated by `METRICS_V2_WRITE_ENABLED`:

1. Decode the Avro batch (the same `METRICS_AVRO_SCHEMA` records capture-logs produced — value buffer is currently passed through opaquely, so this adds the first decode in this hop; measure CPU, it is the main new cost).
2. For each record, build the canonical Prometheus label set: `resource_attributes` ∪ datapoint `attributes` (datapoint wins on collision, matching Snuffle's `posthog` layout precedence) + `service_name` (as label `service_name` if not already present) + `__name__ = metric_name`. **No `__str` suffixes anywhere in v2** — the type-tag suffix is a metrics1-ism; numeric attributes are stringified (Prometheus labels are strings). **[INFERRED precedence — mirrors `postHogLabelMap`; confirm with Rory, Q6.]**
3. Compute the series id with a byte-exact port of Snuffle's `remoteWriteSeriesIdentityLabels` (xxhash64 over length-prefixed sorted pairs; use `xxhash-wasm` or equiv). Port the Go test vectors into jest fixtures so the implementations can never drift silently.
4. Emit rows to the four topics (samples / series / exemplars / metadata) per §5.3–5.5.

### 5.3 Series dedup + re-emission

Per-pod in-memory LRU keyed `(team_id, id)` with value = last-emitted-at. Emit a `metrics_series` row when (cache miss) OR (now − last-emitted > `SERIES_REEMIT_INTERVAL`, default 4h). `min_time`/`max_time` = the batch's observed min/max for that series. Consequences:

- duplicate series rows across pods/restarts/re-emissions are fine (reads `GROUP BY id`; ReplacingMergeTree collapses on merge);
- `max_time` freshness is bounded by the re-emit interval, which makes the series TTL (§4.1) and Snuffle's min/max pruning fallback correct;
- label-index volume is bounded by the same cache (it derives from series inserts).

No Redis coordination needed — wrong-side-of-cache costs only a duplicate tiny row. **[INFERRED — this whole subsection is our design, not Rory's; his writer dedups against CH instead. Q2.]**

### 5.4 Histograms and summaries → classic per-`le` series

For `metric_type IN (histogram, exponential_histogram)` (capture-logs already flattens expo-histograms to explicit bounds/counts):

- per bound `b_i`: a sample on series `{__name__="<name>_bucket", le="<b_i>", ...labels}` with value = **cumulative** count `Σ c_0..c_i` (OTel bucket counts are per-bucket; Prometheus `le` buckets are cumulative — the consumer does the running sum);
- one `le="+Inf"` bucket with the total count;
- `<name>_sum` (the record's `value`) and `<name>_count` (the record's `count`).

For `metric_type = summary`: `<name>{quantile="q"}` series per quantile pair (undoing the float-bits-in-`histogram_counts` packing metrics1 uses) + `_sum`/`_count`.

This is precisely the shape Prometheus scrape produces, so `histogram_quantile` works out of the box in Snuffle's engine and the QL-6 implementation can aggregate `le` buckets without bounds-equality gymnastics. Costs to acknowledge: series count multiplies by (#buckets + 2) per histogram family, and sample volume likewise — but each sample is ~3 bytes, so an exploded histogram still costs a fraction of one metrics1 histogram row with maps + two arrays. Delta-temporality histograms have the same caveat as counters (Q4).

### 5.5 Metadata

Emit one `metrics_metadata` row per `(team_id, metric_family_name)` per `METADATA_REEMIT_INTERVAL` (default 1h, same LRU pattern). Family name = base name with `_bucket`/`_sum`/`_count` stripped for exploded types. `help` is empty (OTLP description is not currently carried through the Avro schema — adding it is a capture-logs follow-up, noted as nice-to-have).

### 5.6 Dual-write guarantees

- The v1 path (`clickhouse_metrics` topic → `kafka_metrics_avro` → `metrics1`) is **byte-for-byte untouched**. The v2 produce is additive and best-effort: a v2 produce failure increments a counter and (optionally) DLQs to `ingestion-metrics-dlq`, but never fails the v1 produce or the offset commit. During transition, metrics1 remains the source of truth.
- Flag rollout: `METRICS_V2_WRITE_ENABLED` env (chart value), optionally `METRICS_V2_WRITE_TEAMS` allowlist for a staged start (team 2 first — the internal-infra team per checkpoint-1).

## 6. Read path

### 6.1 PostHog QL (the `attribute_field()` seam)

The QL stack (QL-0…QL-7) builds everything against `metrics1` with two properties that make the flip cheap: (1) `attribute_field(name, scope)` is the **sole** construction site for attribute access, and (2) the wire shape `[MetricSeries]` never exposes storage. The flip (SR-4) is internal to `products/metrics/backend`:

- Register HogQL tables for the new layout in `posthog/hogql/database/schema/metrics.py`: `posthog.metrics_samples` (`metrics_samples_dist`), `posthog.metrics_series` (`metrics_series_dist`), `posthog.metrics_label_index` (`metrics_label_index_dist`), alongside the existing `posthog.metrics`.
- `MetricQueryRunner` gains a layout switch (instance setting / feature flag `METRICS_SCHEMA_V2_READS`, per-team overridable for staged rollout). v2 query shape, mirroring Snuffle's discipline:
  1. resolve matching series ids: `metric_name` predicate on `metrics_series` + one `id IN (SELECT id FROM metrics_label_index WHERE team_id ... AND label_name = ... AND label_value <op> ...)` membership per attribute filter — i.e. `attribute_field(name)` in filter position compiles to a label-index membership instead of a map subscript;
  2. aggregate `metrics_samples` over those ids on the interval grid (existing bucket ladder / QL-4 grid unchanged);
  3. group-by labels (`attribute_field` in group-by position) come from `JSONExtractString(labels_json, name)` over the *selected series set only* — never over samples.
- `scope=resource|attribute` loses meaning in v2 (one merged label set). `auto` becomes the only real semantic; `resource`/`attribute` are accepted and treated as `auto` with a deprecation note in the contract docstring. **[INFERRED — needs a contracts decision in QL-3 to keep v2-forward labels scope-free.]**
- `MetricNamesQueryRunner` → `SELECT DISTINCT metric_name FROM metrics_series` (PK prefix scan, faster than the skip-index scan on metrics1); `metric_type` hint comes from `metrics_metadata`. `HasMetricsQueryRunner` → `EXISTS` on `metrics_series`. Attribute discovery for pickers → `metrics_label_index` (replaces `metric_attributes` reads after the flip).
- `rate`/`increase` (QL-5): same `clamp_min(runningDifference, 0)` per-id pattern over samples ordered by `(id, timestamp)`; temporality consult moves from the per-row column to a `metrics_metadata` lookup.
- `histogram_quantile` (QL-6): aggregates `_bucket` series by `le` label — simpler than the metrics1 bounds-arrays path.
- The raw SQL editor tab keeps `posthog.metrics` (metrics1) until deprecation; `posthog.metrics_samples`/`_series` are additionally exposed for power users.

### 6.2 Snuffle flip

The logs-cluster Snuffle instances currently run `snuffle_schema_layout: posthog` (reading `metrics1`). Rather than flipping in place, run **both layouts side by side during transition**:

- Add a second systemd instance (ansible role param) `snuffle-v2` on port **9092**, `CH_SCHEMA_LAYOUT=current` with default table names, same `/t/<team_id>` tenancy. Grafana gets a second Prometheus datasource pointed at it; parity comparison is two panels side by side.
- **Gotcha (from `config.go`):** when the metrics layout is `current`, `CH_LOG_SCHEMA_LAYOUT` *defaults to `snuffle`*, not `posthog` — a naive in-place flip would silently break the LogQL datasource over `logs34`. Any `current`-layout instance on the logs cluster must set `snuffle_log_schema_layout: posthog` explicitly (or disable the Loki endpoints on the v2 instance).
- End state (SR-5): the primary instance (9091) flips to `current` (+ explicit log layout pin), the v2 instance is removed, the Grafana datasource flips, and `CH_HISTOGRAMS_TABLE`/`CH_EXEMPLARS_TABLE`/`CH_METRICS_TABLE` get their defaults back (they're empty-string-disabled in the posthog layout).

### 6.3 Parity validation plan

1. **Fixture-level (CI):** extend `seed_metric()` to write both layouts (it already knows the canonical row; v2 seeding reuses the consumer's hashing/explosion functions via a small shared vector file to stay byte-identical). Parameterized tests run every QL query test against both layouts and assert equal `[MetricSeries]` output (exact for sum/count, 1e-9 tolerance for float aggregations).
2. **Dual-read shadow (dev, then prod):** a `MetricQueryRunner` debug mode (`compare_layouts=true`, internal staff only) runs both layouts, returns v1, and logs structured diffs (series-set symmetric difference, max point delta) to a counter + sampled log lines. Run it for the team-2 dashboards for ≥1 week of dual-write before any flip.
3. **PromQL plane:** replay a fixed query corpus (the ~60-panel `logs.json` Grafana dashboard queries + the TSBS-style selectors Snuffle benchmarks with) against `:9091` (posthog layout) and `:9092` (current layout) for the same time windows; diff JSON responses with a tolerance-aware comparator. Known acceptable diffs to whitelist: exploded histograms exist only in v2; `le` series visible in v2 series listings; metadata endpoint non-empty only in v2.
4. **Volume/cost report:** after 2 weeks of dual-write, `system.parts` comparison of bytes-on-disk per sample for metrics1 vs (samples+series+label_index) — the headline number that justifies the cutover, expected ~10x.

## 7. What this fixes / costs (honest ledger)

Wins beyond disk: PromQL histogram support; metadata API; faster name discovery; no `__str`-suffix bug class (the alias/`left(k,-5)` machinery disappears); `uuid` gone; series-level GC.

Costs/risks: an Avro decode+re-encode hop in the consumer (CPU); four more topics + four Kafka tables + five MVs to operate (mitigated: thin MVs, lag MVs, same alerting pattern); series-id hash becomes sacred shared logic between TS and Go (mitigated: shared test vectors); attribute values are stringified (numeric range filters over attributes — `attributes_map_float` — have no v2 equivalent; the QL layer must treat numeric attribute filters as string equality or pre-declared labels, flagged to product); delta-temporality counters remain wrong-ish under `rate()` in both layouts (unchanged, Q4).

## 8. Migration / rollout

Sequencing rule (from checkpoint-1): QL/MCP stack proceeds on metrics1 throughout; SR track is parallel; flip last.

| step | artifact | repo | apply mechanism |
|---|---|---|---|
| SR-1 | this doc → `docs/internal/metrics/schema-v2.md` | posthog PR | review by Rory/Frank/Bryan |
| SR-2a | `bin/clickhouse-metrics-v2.sql` + `posthog/clickhouse/metrics/*.py` builders + NEEDS.md runbook delta | posthog PR | local: `bin/clickhouse-metrics-init`; dev/prod: manual `clickhouse-client` apply (no migration framework for the logs cluster — same standing gap as metrics1, flagged again) |
| SR-2b | 4 WarpStream topics | posthog-cloud-infra PR (terraform, mirrors #8321) | terraform apply (infra team) |
| SR-2c | dev CH apply | — | manual, Bryan/Rory pattern; verify ZK paths against live metrics1 first |
| SR-3 | consumer dual-write (`METRICS_V2_WRITE_ENABLED`) | posthog PR (nodejs) + charts PR (env flag, dev first) | normal deploy |
| SR-4 | QL seam flip behind `METRICS_SCHEMA_V2_READS` + parity tooling | posthog PR(s) | flag rollout: local → dev team 2 → dev all → prod team 2 → prod all |
| SR-5 | snuffle-v2 instance, then layout flip + Grafana datasource | posthog-cloud-infra PR (ansible) + charts PR (Grafana values) | ansible run on CH hosts (Rory) |
| SR-6 (later) | stop v1 writes; drop `kafka_metrics_avro*`, `metrics1`, `metric_attributes` MVs after retention window | posthog PR (delete local DDL) + manual prod DROP runbook | only after ≥30 d of green parity and the SQL-editor deprecation |

### 8.4 Prod apply runbook delta (NEEDS.md)

Same discipline as METRICS-PROD-APPLY.md: one statement at a time, `ON CLUSTER <verified cluster name>`, wait for status=0 on every node; **first** read the live `metrics1` engine string on each prod cluster and substitute its ZK path convention and cluster name into §4 DDL; Kafka tables last (they start consuming immediately — create them only after the consumer is producing to the topics, or create with `kafka_thread_per_consumer` and detach until ready). Rollback DDL (drops in reverse dependency order: MVs → Kafka tables → Distributed → inner tables) ships in the same runbook.

### 8.5 Backfill: none

metrics1 retention is short and the product is alpha. Plan: dual-write for the full product lookback window (≥30 d), then flip reads; v2 history starts at SR-3 enablement. A best-effort `INSERT INTO ... SELECT` backfill from metrics1 is *possible* for gauges/sums (the series-id computation in SQL is the same problem as option (a) — feasible as a one-off offline job via the consumer codepath replaying from metrics1 exports, but not worth it for alpha). If the flip date arrives with <30 d of v2 data, the QL layer can union layouts by time range — explicitly a contingency, not the plan.

### 8.6 Rollback

Reads: flip `METRICS_SCHEMA_V2_READS` off (instant, metrics1 never stopped being written). Writes: flip `METRICS_V2_WRITE_ENABLED` off; v2 tables go stale but harmless; re-enabling resumes cleanly (series re-emission heals the dictionary). Schema: drop runbook in §8.4. Snuffle: revert ansible var; the side-by-side v2 instance means the primary datasource never breaks mid-transition.

## 9. Open questions for Rory / team

1. **Q1 — series-id hash contract.** We port `remoteWriteSeriesIdentityLabels` byte-for-byte (xxhash64, length-prefixed sorted pairs incl. `__name__`). Is that scheme stable from your side / would you take a shared test-vector file into the snuffle repo? Any other current/future writer to these tables we must stay consistent with? (The ops-cluster store is separate, so we believe no — confirm.)
2. **Q2 — series freshness model.** Your writer dedups via CH lookup and never refreshes `min_time`/`max_time`; we propose Kafka at-least-once + per-pod LRU + periodic re-emission + ReplacingMergeTree(max_time). Reads tolerate both (GROUP BY id). Any objection — and is this why `metrics_series_activity`/`metrics_label_postings` exist as empty templates (an abandoned alternative)? Should we adopt the activity-table idea instead of re-emission?
3. **Q3 — TTLs.** 30 d on samples/histograms/exemplars, max_time+30 d on series, none on label_index/metadata. Sane for the logs cluster? Any `ttl_only_drop_parts` interplay with the Replacing engines we should know about?
4. **Q4 — delta temporality.** OTel SDK pushes can be delta; `rate()` assumes cumulative in both layouts. v2 records temporality in `metrics_metadata` but stores values as-emitted. Acceptable for now, or do you want delta→cumulative (or delta-as-gauge tagging) at the consumer before we commit the layout?
5. **Q5 — histograms.** Plan A = classic per-`le` explosion at the consumer; `metrics_histograms` created but unwritten. Would you rather we also write prompb *custom-bucket* native histograms (Prometheus ≥3 supports custom values) so the native table isn't dead weight — or is per-`le` exactly what you'd do?
6. **Q6 — label precedence.** Datapoint attribute beats resource attribute on key collision; `service_name` resource attr surfaces as label `service_name` (matching your `posthog` layout's `postHogLabelMap`). Confirm this is the precedence the `current` layout should see from us.
7. **Q7 — multi-tenant limits.** Snuffle has global `CH_MAX_SERIES`/`PROMQL_MAX_SAMPLES` only. Before exposing the PromQL plane per-team to customers, do we need per-tenant limits in snuffle, or do we gate at the PostHog proxy (auth + team resolution happens there anyway)?
8. **Q8 — sample timestamp snapping.** Your remote-write path snaps timestamps to 15 s buckets (`REMOTE_WRITE_SAMPLE_INTERVAL`). We plan to keep raw OTel timestamps (ms). Any read-path assumption (grid functions, instant-query single-bucket optimization) that prefers snapped timestamps enough to justify snapping at the consumer?
9. **Q9 — prod ZK paths/cluster names.** Confirm the exact ReplicatedMergeTree path + cluster name conventions per prod logs cluster for the runbook (Bryan's "dev has different zk paths" caveat), and whether `index_granularity = 1024` is what you want on the customer-volume samples table or it should match metrics1's 8192.
10. **Q10 — numeric attributes.** `attributes_map_float` has no v2 home (labels are strings). Fine to drop numeric-typed attribute filtering, or does anything (alerting thresholds on label values?) need it preserved?

