# Metrics foundation: ingest-side series identity (align to Snuffle's default layout)

## Decision

Adopt Snuffle's **default layout** for the raw-metrics (events-model) store:
the series identity is **assigned once at ingest** and ClickHouse only stores it.
We do **not** use Snuffle's experimental "PostHog layout", which computes identity inside ClickHouse via `cityHash64`.

This keeps Rory's disk win (the series/samples split) intact, fixes the join, and deletes the workaround machinery we accumulated.

## Why (root-cause recap)

The merged events-model adopted the variant of Snuffle that **recomputes the series fingerprint in ClickHouse materialized views**
(`cityHash64(metric_name, service_name, mapSort(resource_attributes), mapSort(attributes))`, duplicated in the `metric_series` and `metric_samples` MVs).

In production this produced two distinct, locally-unreproducible ClickHouse hashing pathologies:

1. **Disjoint fingerprints** — the two MVs hashed the same row to different values, so `metric_samples` and `metric_series` never joined (0% join, fully broken).
2. **Cardinality collapse** — when the fingerprint is computed in an MV that _also_ materializes the hashed map as a stored column, the hash becomes lossy: in prod, 43,927 true distinct series collapsed to ~2,000.

Neither reproduces in local ClickHouse 26.3 with synthetic data (8 attempts), i.e. it is environmental (Kafka source / real data shape / cluster settings).
Seven candidate ClickHouse-side fixes (explicit casts, `toString`, column-type changes, a decoder→`Null`→chain) either failed or only achieved consistency _at the collapsed cardinality_.

The lesson is the one every production TSDB already encodes:
**identity is an ingest-time concern; the storage engine stores a pre-computed id and never recomputes it.**
Prometheus (`labels.Hash()`), VictoriaMetrics (TSID), Mimir/Cortex, Sentry (Snuba indexer), and **Snuffle's own default layout** all do this.
Snuffle's "PostHog layout" is the only one that hashes in ClickHouse — and it is the one that broke.

## Architecture

### 1. Identity at ingest — `rust/capture-logs`

Compute the series id once when building each metric row (`metric_record.rs::build_number_row` and the histogram path), and ship it in the Avro payload.

- `series_fingerprint: u64` is computed from a **canonical** serialization of everything stored per-series:
  `(metric_name, metric_type, service_name, sorted(resource_attributes), sorted(attributes))`.
  Sort the key/value pairs (e.g. collect into a `BTreeMap` or sort a `Vec`) so map iteration order can never change the id.
  `metric_type` and `service_name` are in the hash (not just the labels) because `metric_series` stores them per fingerprint — omitting either would let a gauge and a sum (or two services) with identical labels collapse onto one deduped row, last writer winning the metadata.
- Hash function: any stable, fast, well-distributed 64-bit hash (e.g. `xxh3` via `xxhash-rust`).
  **It does not need to match ClickHouse's `cityHash64`** — nothing in ClickHouse recomputes it, so there is no cross-language byte-compatibility requirement. This is the whole point.
- `team_id` is **not** part of the hash. It stays a separate dimension; every table is keyed `(team_id, metric_name, series_fingerprint)`, so two tenants with the same metric+labels get distinct rows with no collision. (Matches Snuffle's `ORDER BY (team_id, metric_name, id)`.)
- A golden test asserts the Rust id is stable across runs and label-order permutations.

> Naming: we keep the existing column name `series_fingerprint` (it is still a hash of the labels — just computed at ingest, not in ClickHouse), to avoid churning the merged HogQL tables / query runner / contracts. Semantically it is now "supplied by the writer."

### 2. Storage schema — three tables (Snuffle default)

| This product                                      | Snuffle default       | Purpose                                           |
| ------------------------------------------------- | --------------------- | ------------------------------------------------- |
| `metric_series` (`ReplacingMergeTree(last_seen)`) | `metrics_series`      | One row per unique series; **labels stored once** |
| `metric_samples` (`MergeTree`, 30d TTL)           | `metrics_samples`     | The hot table; **tiny rows**                      |
| `metric_label_index` (`ReplacingMergeTree`)       | `metrics_label_index` | Inverted index for label pruning at scale         |
| (`trace_id`/`span_id` inline on `metric_samples`) | `metrics_exemplars`   | Metric→trace pivot                                |

**`metric_series`** — `team_id, metric_name, series_fingerprint, labels, metric_type, unit, service_name, last_seen`.
`ORDER BY (team_id, metric_name, series_fingerprint)`.
Labels are stored **once per series**. Keep them as the existing decoded `Map`s (`resource_attributes`, `attributes`) — this is now safe because **nothing hashes them anymore**, and it matches how logs/traces store attributes. (Snuffle uses an opaque `labels_json String` to avoid `JSONExtract` in the query path; we can switch to that later if Map filtering on the series table becomes hot, but it is not required to fix the bug.)

**`metric_samples`** — `team_id, metric_name, series_fingerprint, timestamp, value, trace_id, span_id, trace_flags`.
`ORDER BY (team_id, metric_name, series_fingerprint, timestamp)`, 30-day TTL.
This is where the ~89% disk win lives: no label maps, no uuid — just the id + the number.

**`metric_label_index`** — `team_id, metric_name, label_key, label_value, series_fingerprint`.
`ORDER BY (team_id, metric_name, label_key, label_value, series_fingerprint)`.
Lets "find series where `topic_name='ingestion-logs'`" be a range scan instead of a `JSONExtract`/map scan over the series table.
**Phaseable:** v1 can filter the (small, deduped) `metric_series` table directly and add this index as a fast-follow when series cardinality demands it. Included here because it is part of Snuffle's default layout and the eventual scale story.

### 3. Ingest pipeline — ClickHouse is dumb storage

```text
kafka_metrics_avro
  ├─ kafka_metrics_avro_mv         → metrics1            (unchanged; the existing wide table)
  ├─ kafka_metrics_avro_to_series  → metric_series       (SELECT + INSERT, reads series_fingerprint from Avro)
  └─ kafka_metrics_avro_to_samples → metric_samples      (SELECT + INSERT, reads series_fingerprint from Avro)
        └─ metric_series_to_label_index → metric_label_index   (arrayJoin labels; phase 2)
```

The two MVs become **passthroughs**: they read `series_fingerprint` straight off the Avro column.
No `cityHash64`, no `mapApply`/`JSONExtractString` for identity, no decoder MV, no `metric_events_decoded` `Null` table, no chained MVs.
Because neither MV recomputes anything, the two tables physically cannot diverge or collapse.

### 4. Read path

- **Drill-down (samples for a metric):** filter `metric_samples` by `(team_id, metric_name, time window)`, join to `metric_series` on `series_fingerprint` for labels. `MetricEventSamplesQueryRunner` is unchanged in shape — it just joins on an ingest-supplied id.
- **Filter by label:** filter `metric_series` (small) directly in v1; via `metric_label_index` intersection at scale.
- **Metric→trace pivot:** `trace_id` on `metric_samples`. **Known gap:** exemplars are not populated upstream yet (`_exemplars` is unused in `metric_record.rs`), so `trace_id` is empty today — separate ingestion work, independent of this foundation.

## What gets deleted

- The `cityHash64(... mapApply(JSONExtractString ...) ...)` identity expression in both ingest MVs.
- The decoder MV, the `metric_events_decoded` `Null` table, and the two chained MVs (the workaround).
- Any bloom-filter indexes that only existed to support map-based identity lookups (re-add deliberately for query pruning, not identity).

Net: fewer moving parts than today, and the parts that remain are all on Snuffle's proven path.

## Migration / rollout

1. **PR1 (rust):** `capture-logs` computes `series_fingerprint` and adds it to `KafkaMetricRow` + the Avro schema. Golden test (stable, order-independent). Ship and confirm the field is populated on the topic.
2. **PR2 (clickhouse):** simplify the two MVs to passthroughs reading `series_fingerprint`; delete the decoder/`Null`/chain; (optional) add `metric_label_index` + its MV. A ClickHouse test asserts `metric_series` and `metric_samples` agree on a multi-label row (the test the original single-row check was missing).
3. **Prod re-apply (per logs node, both regions):** drop the current MVs (and the decoder/`Null`/chain), `TRUNCATE metric_series` / `metric_samples`, create the passthrough MVs. Tables refill consistently from the next message.
4. **Validation — now BOTH must hold** (the CH-hashing version could only ever get one):
   - `orphans = 0` (every sample's `series_fingerprint` is in `metric_series`), **and**
   - `uniqExact(series_fingerprint)` ≈ `uniqExact((metric_name, metric_type, service_name, resource_attributes, attributes))` from `metrics1` (no cardinality collapse).
   - HogQL `pct_joined ≈ 100` across all metrics.

## Current prod state

EU is in the **collapsed-but-consistent** state from the last workaround (do not build/demo on it). It is not worse than before and not live, so no urgent rollback — but it is not fixed until this rollout lands. **US has not been touched** and should not be until EU validates with both checks above.

## Appendix: alternative considered

A pure **wide-table** foundation (one row per sample with labels, `metrics1`-style, à la ClickStack/SigNoz/Uptrace) is also proven and even simpler — but it is exactly the fat shape Rory's review rejected on disk grounds (~100× per-sample overhead at our cardinality). The split + ingest-side identity keeps that disk win while being equally correct, so it is the better foundation for a multi-tenant product.
