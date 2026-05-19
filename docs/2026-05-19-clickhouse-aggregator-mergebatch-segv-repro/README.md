# Repro: SIGSEGV in `Aggregator::mergeBatch` on ClickHouse 26.3.10.60

Companion to [../2026-05-19-clickhouse-aggregator-mergebatch-segv.md](../2026-05-19-clickhouse-aggregator-mergebatch-segv.md).

The production crash log on `prod-us-iad-ch-1e-offline` (CH `26.3.10.60`,
aarch64, git `6a6d2d137d…`) shows four SIGSEGVs with this signature:

```
top  : IAggregateFunctionHelper<...>::mergeBatch
       (AggregateFunctionMerge   for Row 1 — argMinMerge(Nullable(String), DateTime64))
       (AggregateFunctionAny<SingleValueDataString>  for Rows 2–4 — anyIf(String, ...))
       Aggregator::mergeStreamsImpl<AggregationMethodString>
       MergingAggregatedBucketTransform
fault: SEGV_MAPERR (address not mapped)
```

This directory contains two self-contained SQL scripts that **reliably crash
ClickHouse 26.3.10.60 on aarch64 in under a second**, with the same call path
and the same non-pointer fault address (`0x010001000100`) as production.

## Files

| File | Maps to | Aggregate the bug hits |
|---|---|---|
| [`repro_a_argminmerge.sql`](repro_a_argminmerge.sql) | row 1 (HogQL session_replay_events listing) | `AggregateFunctionMerge` over `AggregateFunction(argMin, Nullable(String), DateTime64)` |
| [`repro_b_anyif_string.sql`](repro_b_anyif_string.sql) | rows 2–4 (delete-recordings activity) | `AggregateFunctionAny<SingleValueDataString>` over plain `String` |

## How to run (locally, against this repo's docker compose)

The PostHog dev stack already runs `clickhouse/clickhouse-server:26.3.10.60`
on aarch64 in container `posthog-clickhouse-1` — same build as the crashing
production node.

### Repro B (simplest, ~2s end-to-end)

```bash
docker exec -i posthog-clickhouse-1 clickhouse-client --multiquery \
  < docs/2026-05-19-clickhouse-aggregator-mergebatch-segv-repro/repro_b_anyif_string.sql
```

The client returns a `Connection reset by peer` (the server died mid-query).
Wait ~2s for `clickhouse-server` to restart, then confirm:

```bash
docker exec posthog-clickhouse-1 clickhouse-client -q \
  "SELECT event_time, hex(fault_address), trace_full[1] \
   FROM system.crash_log ORDER BY event_time DESC LIMIT 1 FORMAT Vertical"
```

Expected:

```
event_time:         …
hex(fault_address): 010001000100
trace_full[1]:      <addr of IAggregateFunctionHelper<AggregateFunctionAny<SingleValueDataString>>::mergeBatch>
```

### Repro A (run in two clients)

`repro_a_argminmerge.sql` is split into two sections. The single-session
`--multiquery` path occasionally trips an *unrelated* `LOGICAL_ERROR`
("Columns are assumed to be of identical types … in Nullable") on
`max(UInt8) = 0` over `remote()`, which masks the crash. Run setup and the
crashing query separately:

```bash
# section 1: DDL + INSERT (everything before the "CRASHING QUERY" banner)
awk '/^-- ============= CRASHING/{exit} {print}' \
  docs/2026-05-19-clickhouse-aggregator-mergebatch-segv-repro/repro_a_argminmerge.sql \
  | docker exec -i posthog-clickhouse-1 clickhouse-client --multiquery

# section 2: the crashing SELECT (everything after the banner)
sed -n '/^-- ============= CRASHING/,$p' \
  docs/2026-05-19-clickhouse-aggregator-mergebatch-segv-repro/repro_a_argminmerge.sql \
  | tail -n +2 \
  | docker exec -i posthog-clickhouse-1 clickhouse-client
```

The second command returns either a `Connection reset by peer` or a
`LOGICAL_ERROR` (the server dies on one thread while another raises the
typed exception). Confirm via `system.crash_log` as above. The top frame
will be `…<AggregateFunctionMerge>::mergeBatch`.

## What makes the bug trigger

This is empirical, from progressively reducing the production query against
the local 26.3.10.60 container. The minimum set of conditions:

1. **`GROUP BY` on a String key** → forces `AggregationMethodString` and
   arena-allocated keys (`HashMapTable<string_view, char*>`).
2. **At least one aggregate state that owns String data in the arena** —
   either `anyIf(String, ...)` or `argMinMerge(...)` over an
   `AggregateFunction(argMin, String, …)` column.
3. **Two-level aggregation** (`group_by_two_level_threshold` must be exceeded
   — easiest way is high-cardinality GROUP BY + a low threshold setting).
4. **The bucket-merge path** (`MergingAggregatedBucketTransform`). On a
   single node this requires a *distributed* query — the repros use
   `remote('clickhouse,clickhouse', …)` so the same server addresses itself
   twice as two pseudo-shards. `distributed_aggregation_memory_efficient = 1`
   is the default and must stay on.

In addition, **the trigger is layout-dependent in the arena**:

- Reordering the aggregates in the `SELECT` list flips the crash on/off —
  `min(t), max(d), anyIf(v)` crashes, but `max(d), anyIf(v), min(t)` does not.
- Dropping `max(d)` (`max(UInt8)`) from Repro B makes it stop crashing —
  even though that aggregate has no String state of its own. The crash
  needs the *combination* of state slot sizes/layout that put the
  `SingleValueDataString` pointer at the offset the bug touches.
- Empirically: `min(DateTime64) + max(UInt8) + anyIf(String, ...)` reliably
  crashes; `anyIf(String, ...)` alone does not.

This is consistent with the original diagnosis in the parent doc: the
`MergingAggregatedBucketTransform` mis-handles arena-resident state slots
during two-level merge.

## Mitigations: what works and what doesn't

The parent doc *hypothesized* two server-side workarounds; the local repro
falsifies both and validates a third.

| Setting | Result on local repro |
|---|---|
| `distributed_aggregation_memory_efficient = 0` | **Still crashes.** The crash just moves from `MergingAggregatedBucketTransform → mergeStreamsImpl<AggregationMethodString>` to `Aggregator::mergeBlocks → mergeStreamsImpl<AggregationMethodStringNoCache<TwoLevelStringHashMap>>`. The bug is in *any* two-level String-keyed merge path, not specifically the bucket transform. |
| `group_by_two_level_threshold = 100000000` (huge) | **Still crashes.** The two-level buckets are produced on the remote shards and shipped to the initiator regardless of the initiator's threshold setting. |
| `max_threads = 1` | **Still crashes.** |
| `allow_experimental_analyzer = 1` | ✅ **No crash.** Both repros return results. The new query analyzer plans the same SQL through a different code path that does not hit this bug. |

So the actually-verified non-rollback mitigation on `26.3.10.60` is:

```sql
SETTINGS allow_experimental_analyzer = 1
```

The PostHog production node is running with the legacy planner
(`allow_experimental_analyzer = false` in the changed_settings dump from
the crash log). Flipping the analyzer on for the affected queries (via
profile or per-query SETTINGS) avoids the bug. The trade-off is the usual
analyzer-on/off semantic differences — not a one-line setting change you
ship without testing.

The safest mitigation remains **rolling back the offline node** to the
previous CH version.

## Upstream

Search/file at `github.com/ClickHouse/ClickHouse/issues` with these
keywords:

```
MergingAggregatedBucketTransform mergeBatch SEGV AggregationMethodString
SingleValueDataString AggregateFunctionMerge 26.3
```

Attach: both `.sql` files in this directory, the `system.crash_log` entry,
and the call stack from `clickhouse-server.err.log`. The PostHog production
crash dump is **not** required to file — the repro is self-contained.
