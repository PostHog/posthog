# Read-your-own-writes consistency research

## The problem

The preaggregation system INSERTs data into ClickHouse and immediately SELECTs it back. In PostHog's self-hosted distributed+replicated ClickHouse cluster, this is unreliable at two levels:

1. **Distributed table layer**: INSERT into `preaggregation_results` (distributed table) routes to `sharded_preaggregation_results` (sharded `ReplicatedAggregatingMergeTree`) via `sipHash64(job_id)`. By default this is **async** — data is written to the initiator node's local filesystem and sent to the target shard in the background. The INSERT returns before the data is queryable.

2. **Replication layer**: Even after data reaches the target shard, only 1 replica acknowledges the write by default. A SELECT hitting another replica gets stale/empty results.

Table definitions: [`posthog/clickhouse/preaggregation/sql.py`](../../../../posthog/clickhouse/preaggregation/sql.py)

## ClickHouse settings investigated

All settings below are **per-query** — passed via `settings` parameter to `sync_execute` or as `SETTINGS` clause on SQL. They do not affect other queries on the cluster.

### `distributed_foreground_insert=1` (INSERT setting)

Controls whether INSERTs into a Distributed table are synchronous or asynchronous.

- **Default**: `0` (async) — data written to initiator's local temp directory, background thread sends to target shard
- **With `1`**: data sent directly to target shard in the foreground, INSERT blocks until shard acknowledges
- **Latency**: adds network RTT to slowest shard (~1-10ms in co-located cluster)
- **ZK/Keeper load**: none — this is about the Distributed table routing, not replication
- **Contention**: none — just holds the connection open longer
- **Other queries affected**: no

Previously named `insert_distributed_sync`.

**Already enabled globally**: PostHog's ClickHouse config sets `insert_distributed_sync=1` in `docker/clickhouse/users.xml`. This means layer 1 (distributed table routing) is already solved for all queries. The `posthog/dags/sessions.py` DAG explicitly overrides this to `0` for large INSERTs to avoid OOM, confirming the global default is `1`.

Sources:

- [ClickHouse settings docs](https://clickhouse.com/docs/operations/settings/settings#distributed_foreground_insert)

### `insert_quorum='auto'` (INSERT setting)

Sets the minimum number of replicas that must acknowledge a write before the INSERT returns.

- **Default**: `0` (disabled) — INSERT returns after writing to 1 replica
- **`'auto'`**: majority of replicas = `(num_replicas / 2) + 1`. For 2 replicas → 2 (all). For 3 → 2.
- **Latency**: 20-100ms additional (replication wait dominates, plus 2-3 extra ZK transactions per INSERT on top of the ~10 that a normal INSERT already does)
- **ZK/Keeper load**: 2-3 extra ZK writes per INSERT — registers quorum status, waits for replica confirmations, updates `quorum/last_part`
- **Contention**: none between queries — each INSERT independently tracks its quorum
- **Other queries affected**: no (ZK path is per-table, no cross-table impact)
- **Failure mode**: if a replica is down and quorum can't be met, INSERT fails after `insert_quorum_timeout` (default 60s) with `TOO_FEW_LIVE_REPLICAS`

Only works with ReplicatedMergeTree family tables, not Distributed tables directly. The quorum is enforced on the underlying replicated table after the distributed layer routes the data.

**Availability risk with `'auto'`**: quorum = `(num_replicas / 2) + 1`, so with 2 replicas quorum is 2 (all). If one replica goes down, no quorum INSERTs can succeed — they all fail with `TOO_FEW_LIVE_REPLICAS` after `insert_quorum_timeout` (default 60s). With 3 replicas quorum is 2, so one replica can be down and INSERTs still succeed. This means quorum trades write availability for consistency: in a 2-replica setup, a single replica failure blocks all preaggregation writes (for up to 60 seconds before the timeout error). The preaggregation executor's retry logic would handle the error, but no new preaggregation data can be written until the replica recovers. Without quorum, the system degrades gracefully — writes go to the remaining replica and reads work, just without the read-your-own-writes guarantee.

Sources:

- [ClickHouse settings docs](https://clickhouse.com/docs/operations/settings/settings#insert_quorum)
- [Replication docs](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication)
- [auto quorum PR #39970](https://github.com/ClickHouse/ClickHouse/pull/39970)

### `insert_quorum_parallel` (INSERT setting)

Controls whether multiple concurrent quorum INSERTs can proceed in parallel on the same table.

- **Default**: `1` (parallel, since ClickHouse 20.10)
- **With `1`**: each INSERT independently tracks its quorum via separate ZK entries under `{zk_path}/quorum/parallel/`
- **With `0`**: uses an **exclusive lock** on `{zk_path}/quorum/status` — only one quorum INSERT can be in-flight **per table** at a time, across the entire cluster
- **Failure mode with `0`**: a second INSERT errors immediately with "Quorum for previous write has not been satisfied yet" (does NOT wait — fails fast)

**The lock is NOT held for the entire INSERT.** The contention window is only the quorum registration + replication wait phase:

1. INSERT...SELECT executes (reads events, aggregates) — takes seconds, **no lock**
2. Data written to local part — **no lock**
3. Quorum registered in ZK — **lock acquired** (~1ms)
4. Wait for replicas to confirm — 20-100ms
5. Quorum satisfied — **lock released**

Two concurrent preaggregation INSERTs can execute their heavy SELECT (step 1) simultaneously. They only contend if both reach step 3 within the same ~100ms window. At high INSERT throughput (see [README.md](./README.md) for load context), this is a real concern — with a ~100ms lock hold time, the lock can sustain at most ~10 non-overlapping INSERTs per second to the same table. Beyond that, INSERTs start failing with immediate errors. The executor's retry logic handles these errors (they're retryable), but at high throughput the retry rate would be significant.

**Why parallel was made the default**: the sequential mode was "significantly less convenient to use" because it serialized all writes to a replicated table when quorum was enabled. See [PR #17567](https://github.com/ClickHouse/ClickHouse/pull/17567) and [issue #3950](https://github.com/ClickHouse/ClickHouse/issues/3950).

**Why we might still need `0`**: `select_sequential_consistency=1` does NOT work correctly with `insert_quorum_parallel=1`. The `quorum/last_part` ZK node can't meaningfully track "the last quorum-committed part" when multiple parts are in-flight simultaneously. ClickHouse does not warn about this — it silently gives incorrect results. See [issue #47926](https://github.com/ClickHouse/ClickHouse/issues/47926).

Sources:

- [ClickHouse settings docs](https://clickhouse.com/docs/operations/settings/settings#insert_quorum_parallel)
- [Parallel quorum PR #17567](https://github.com/ClickHouse/ClickHouse/pull/17567)
- [Original feature request #3950](https://github.com/ClickHouse/ClickHouse/issues/3950)
- [Broken with select_sequential_consistency #47926](https://github.com/ClickHouse/ClickHouse/issues/47926)

### `select_sequential_consistency=1` (SELECT setting)

Ensures a SELECT only runs on replicas that have all quorum-committed data.

- **Default**: `0` (disabled)
- **What it does**: reads `{zk_path}/quorum/last_part` from Keeper, checks the local replica has that part (or a merged part containing it). If behind, throws `REPLICA_IS_NOT_IN_QUORUM` — the query **fails** rather than returning stale data. Also filters out non-quorum-confirmed parts from the read set.
- **Latency**: 1 ZK read + local metadata check (~1-10ms)
- **ZK/Keeper load**: 1 read-only ZK op per SELECT
- **Contention**: none
- **Other queries affected**: no
- **Works with `readonly=2`**: yes (it's a query-level setting, not a SYSTEM command)

**Critical**: does NOT work correctly with `insert_quorum_parallel=1` (the default). You must set `insert_quorum_parallel=0` on the INSERT side. ClickHouse does not warn — it silently returns stale data.

Note: this is a **rejection mechanism**, not a routing mechanism. If the load balancer picks a stale replica, the query fails rather than being retried on another replica. Sentry [rejected this approach](https://blog.sentry.io/how-to-get-stronger-consistency-out-of-a-datastore/) for this reason, though their workload is different from ours.

Sources:

- [ClickHouse settings docs](https://clickhouse.com/docs/operations/settings/settings#select_sequential_consistency)
- [Read consistency KB](https://clickhouse.com/docs/knowledgebase/read_consistency)
- [Implementation PR #2863](https://github.com/ClickHouse/ClickHouse/pull/2863)
- [Latency with degraded ZK #22068](https://github.com/ClickHouse/ClickHouse/issues/22068)
- [Bug with empty parts cleanup #44972](https://github.com/ClickHouse/ClickHouse/issues/44972)
- [Sentry blog: stronger consistency](https://blog.sentry.io/how-to-get-stronger-consistency-out-of-a-datastore/)

### `insert_quorum_timeout` (INSERT setting)

- **Default**: 60 seconds
- Maximum time to wait for quorum to be satisfied. If timeout expires, INSERT fails and data is rolled back from all replicas that received it.
- Tune based on replica lag characteristics.

### `optimize_skip_unused_shards` (SELECT setting)

Controls whether the Distributed table prunes shards based on the WHERE clause and the sharding key.

- **Default**: `0` (disabled — SELECT fans out to all shards)
- **With `1`**: coordinator evaluates the sharding key expression for each value in the WHERE clause and routes to only the matching shard(s). For `sipHash64(job_id)` with `WHERE job_id IN (...)`, this routes to exactly the shard(s) holding those job IDs.
- **`force_optimize_skip_unused_shards=1`**: fails the query if shard pruning can't be determined (safety net to catch queries that accidentally fan out)
- **Latency**: slight reduction (fewer shards queried)
- **ZK/Keeper load**: none
- **Contention**: none
- **Other queries affected**: no

Our sharding key is `sipHash64(job_id)` and combiner queries filter by `job_id IN (...)` — a perfect match for this optimization.

Sources:

- [ClickHouse settings docs](https://clickhouse.com/docs/operations/settings/settings#optimize-skip-unused-shards)

### `load_balancing` (SELECT setting)

Controls which replica the Distributed table picks for SELECT queries within each shard.

- **`random`** (default, PostHog's current config in `docker/clickhouse/users.xml`): random healthy replica
- **`in_order`**: always prefers the first replica in the config; deterministic routing. Both INSERT and SELECT will pick the same replica as long as it's healthy.
- **`first_or_random`**: tries first replica, random fallback if it has more errors
- **`nearest_hostname`**: picks by hostname similarity to the querying server
- Per-query setting, can be passed via `settings` param to `sync_execute`

Sources:

- [ClickHouse settings docs](https://clickhouse.com/docs/operations/settings/settings#load_balancing)
- [Sentry blog](https://blog.sentry.io/how-to-get-stronger-consistency-out-of-a-datastore/)

### `SYSTEM SYNC REPLICA table LIGHTWEIGHT` (SQL command, not a setting)

An alternative to `select_sequential_consistency`. Waits for the local replica to catch up on data-movement replication entries (GET_PART, ATTACH_PART, DROP_RANGE) — ignores merges and mutations.

- **Available since**: ClickHouse v23.5 ([PR #48085](https://github.com/ClickHouse/ClickHouse/pull/48085))
- **Latency**: if replica is caught up, returns in milliseconds. Otherwise waits for part fetches to complete.
- **ZK/Keeper load**: reads the replication queue (no writes)
- **Blocks other queries**: no (blocks only the calling connection)

**Why we're not using this**:

- Only syncs the **local replica** on the node where the command runs. The caller's SELECT may go through a different node via the Distributed table, hitting an unsynced replica.
- `ON CLUSTER` variant syncs all nodes but adds latency proportional to cluster size.
- Blocked by `readonly=2` (PostHog's HogQL default). Requires `SYSTEM SYNC REPLICA` privilege. Would need a separate `sync_execute` call with `readonly=False`.
- `select_sequential_consistency` is simpler — 1 ZK read, works as a per-query `SETTINGS` clause, compatible with `readonly=2`.

PostHog already uses `SYSTEM SYNC REPLICA STRICT` in `posthog/dags/common/overrides_manager.py` and `posthog/dags/deletes.py` for cases where consistency matters, but those use direct `Client` connections rather than the `sync_execute` path.

Sources:

- [SYSTEM SYNC REPLICA docs](https://clickhouse.com/docs/sql-reference/statements/system#sync-replica)
- [Faster SYNC REPLICA issue #47794](https://github.com/ClickHouse/ClickHouse/issues/47794)
- [LIGHTWEIGHT PR #48085](https://github.com/ClickHouse/ClickHouse/pull/48085)
- [FROM modifier PR #58393](https://github.com/ClickHouse/ClickHouse/pull/58393)

## Can we verify an INSERT has been replicated?

**Short answer: no, not per-INSERT.** ClickHouse does not return a write token or part name from INSERT statements — there is no `INSERT RETURNING` ([feature request #21697](https://github.com/ClickHouse/ClickHouse/issues/21697)).

System tables that get close but aren't sufficient:

- **`system.parts`**: local to each replica, shows what parts exist on _this_ node. No replication status column. Would need to query every replica to check if a part exists everywhere.
- **`system.replication_queue`**: shows pending replication tasks (`GET_PART`, `MERGE_PARTS`, etc). Can't filter by a specific INSERT. Waiting for `queue_size=0` waits for _all_ replication work, not just yours.
- **`system.replicas`**: aggregate stats (`queue_size`, `inserts_in_queue`, `log_pointer` vs `log_max_index`, `absolute_delay`). Good for monitoring lag, but too coarse for per-INSERT tracking.
- **`system.part_log`**: can match an INSERT's `query_id` to the parts it created (`event_type='NewPart'`), then check other replicas for `event_type='DownloadPart'`. But: has a flush delay, parts may be merged before download (so the part name changes), and requires querying every replica.
- **Keeper paths**: `{zk_path}/quorum/status` is only populated when `insert_quorum` is enabled. No general per-part replication tracking for non-quorum inserts.

Sources:

- [system.parts docs](https://clickhouse.com/docs/operations/system-tables/parts)
- [system.replication_queue docs](https://clickhouse.com/docs/operations/system-tables/replication_queue)
- [system.replicas docs](https://clickhouse.com/docs/operations/system-tables/replicas)
- [INSERT RETURNING feature request #21697](https://github.com/ClickHouse/ClickHouse/issues/21697)

## Approaches considered

### Approach A: Quorum writes + sequential consistency

```text
INSERT: insert_quorum='auto', insert_quorum_parallel=0
SELECT: select_sequential_consistency=1
```

**Pros**: guaranteed correct, well-documented ClickHouse approach, per-query settings only
**Cons**: per-table serialization during quorum wait (~100ms contention window), requires `insert_quorum_parallel=0`
**INSERT latency**: +20-100ms (replication wait)
**SELECT latency**: +1-10ms (1 ZK read)
**Contention risk**: high at scale — lock sustains ~10 INSERTs/second to the table before failures start. Retryable, but significant retry churn at high throughput.

### Approach B: Quorum writes only (no sequential consistency)

```text
INSERT: insert_quorum='auto'
SELECT: no special settings
```

**Pros**: no per-table serialization, simpler
**Cons**: not fully correct — with 3+ replicas per shard, ~33% chance of hitting a stale replica. With 2 replicas, quorum=2=all so it's correct.
**Risk depends on replica count**: safe with 2 replicas, unreliable with 3+.

### Approach C: Quorum writes + SYSTEM SYNC REPLICA

```text
INSERT: insert_quorum='auto'
After INSERT: SYSTEM SYNC REPLICA sharded_preaggregation_results LIGHTWEIGHT
SELECT: no special settings
```

**Pros**: no per-table serialization, correct
**Cons**: only syncs local replica — caller's SELECT may go through different node. `ON CLUSTER` variant is heavy. Blocked by `readonly=2`. More complex implementation.

### Approach D: Write directly to sharded tables

Write to `sharded_preaggregation_results` directly on a specific node, run the SELECT on the same node.

**Pros**: inherent read-your-own-writes, no extra settings needed
**Cons**: significant architectural change — need to know which shard to write to, route both INSERT and SELECT to the same node, bypass the Distributed table layer.

### Approach E: Deterministic replica routing (Sentry's approach)

```text
INSERT: (distributed_foreground_insert=1 is already global)
SELECT: optimize_skip_unused_shards=1, load_balancing='in_order'
```

Sentry [rejected `select_sequential_consistency`](https://blog.sentry.io/how-to-get-stronger-consistency-out-of-a-datastore/) because it _fails_ queries when a replica is behind (it's a rejection mechanism, not a routing mechanism). Instead they use `load_balancing=in_order` so both INSERT and SELECT deterministically prefer the same first replica in the config. Since `distributed_foreground_insert=1` ensures the INSERT synchronously writes to that replica, the subsequent SELECT reads from it.

**Pros**: zero ZK overhead on reads, no per-table serialization, per-query settings only
**Cons**: not formally guaranteed — if the preferred replica goes down between INSERT and SELECT, the fallback replica may be stale (see quorum hardening below). Concentrates preaggregation read/write load on one replica per shard — with 3 replicas, other queries using `random` load balancing distribute evenly across all 3 (including replica 1), so replica 1 gets a disproportionate share of total load. Acceptable when preaggregation is a small fraction of total query volume, but worth monitoring as it grows.
**INSERT latency**: none extra (already global)
**SELECT latency**: none extra (may be slightly faster with shard pruning)

**Optional hardening: add quorum writes.** Adding `insert_quorum='auto'` ensures the INSERT is acknowledged by a majority of replicas before returning. This covers the failover edge case: if replica 1 goes down between INSERT and SELECT, `in_order` falls back to replica 2, which has the data thanks to quorum. Importantly, since we're using `load_balancing='in_order'` instead of `select_sequential_consistency`, we do NOT need `insert_quorum_parallel=0` — parallel quorum (the default) works fine, so there's no per-table lock and no throughput limit. The cost is +20-100ms INSERT latency for the quorum wait.

**Optional performance optimisation: only read from relevant shards.** Depending on the sharding key, `optimize_skip_unused_shards=1` could ensure the SELECT also routes to the correct _shard_ (not just the correct replica within a shard), since our combiner queries filter by `job_id IN (...)` which may be the sharding key.

## Sharding key analysis

The Distributed table currently uses `sipHash64(job_id)` as the sharding key. This means all rows for a single job land on one shard.

The choice of sharding key depends on which consistency approach is used:

**For approach D (shard-local writes)**: the sharding key must localize data for read-your-own-writes. `sipHash64(query_hash)` is the better choice here — it co-locates all jobs for the same query on one shard, so the combiner query (which filters by `query_hash` and `job_id IN (...)`) reads everything it needs from a single shard with no cross-shard consistency concerns. With `sipHash64(job_id)`, you'd get shard-local consistency for the job you just wrote, but other jobs for the same query could be on different shards and might not have replicated yet — a subtle consistency gap even with shard-local writes.

**For approaches A, B, C, E (settings-based consistency)**: consistency comes from ClickHouse settings (quorum, `in_order`, etc.), not shard locality. The sharding key doesn't need to localize a job's data — it could distribute it across shards for better parallelism. Sharding on something like `sipHash64(toString(breakdown_value))` would spread a single large job's rows across shards, giving better write and read parallelism for the `INSERT...SELECT` and combiner queries. The tradeoff is losing `optimize_skip_unused_shards` — every SELECT fans out to all shards — but for preaggregation queries that aggregate across many breakdown values, fanning out to parallelize is what you want anyway.

**Caveats for non-`job_id` sharding keys**:

- `breakdown_value` is `Array(String)` — would need `sipHash64(toString(breakdown_value))` or similar
- If `breakdown_value` is often empty (`[]`), all those rows hash to the same value, creating hotspotting on one shard
- `query_hash` concentrates all jobs for a hot query on one shard (hotspotting risk)

**Current recommendation**: keep `sipHash64(job_id)` for now. It's even, simple, and works with all approaches. Revisit if a single job's data becomes large enough that cross-shard parallelism matters.

## Other approaches investigated but not applicable

- **`max_replica_delay_for_distributed_queries`**: rejects replicas lagging by N seconds, but the granularity is seconds — too coarse for sub-second read-after-write where replication lag is measured in milliseconds.
- **`SYSTEM FLUSH DISTRIBUTED`**: forces async distributed sends to complete, but `distributed_foreground_insert=1` already solves this and is already enabled globally.
- **`distributed_group_by_no_merge`**: performance optimization that skips coordinator-level re-aggregation for single-shard queries — not a consistency mechanism.
- **Kafka coordination layer**: Sentry also built a `SynchronizedConsumer` that uses Kafka commit log topics as a write confirmation barrier. Not applicable to the preaggregation system's `INSERT...SELECT` workload.
- **ClickHouse transactions**: experimental `BEGIN TRANSACTION` / `COMMIT` support exists but is limited to single-table operations on ReplicatedMergeTree, not production-ready, and doesn't directly address read-after-write consistency.
- **Application-level retry**: retry the SELECT if it returns empty/stale results. Probabilistic, not a guarantee — doesn't solve the consistency problem, just masks it with latency.
- **`insert_deduplication_token`**: makes INSERTs idempotent by token, allowing safe retries. But doesn't solve the read side — a retried INSERT still races replication. Also, `INSERT...SELECT` may produce different results on retry if source data changed (new events arrived), so the deduplication token won't match and both INSERTs land.

## ClickHouse Cloud / SharedMergeTree

Not applicable to PostHog (fully self-hosted), but for reference:

- SharedMergeTree writes to shared object storage (S3/GCS) — quorum is inherent
- `insert_quorum` / `insert_quorum_parallel` are effectively no-ops
- `select_sequential_consistency` still exists but "most of the time, you should not be using it" — metadata propagation through Keeper is very low latency
- `distributed_foreground_insert` is still relevant if using Distributed tables for sharding

## Summary table

| Setting                           | Scope                         | ZK ops added | Latency          | Contention               | Impact on other queries                               |
| --------------------------------- | ----------------------------- | ------------ | ---------------- | ------------------------ | ----------------------------------------------------- |
| `distributed_foreground_insert=1` | Global (already set)          | None         | +1-10ms          | None                     | None                                                  |
| `insert_quorum='auto'`            | Per-query                     | 2-3 writes   | +20-100ms        | None                     | None                                                  |
| `insert_quorum_parallel=0`        | Per-query (lock is per-table) | None extra   | None extra       | ~100ms window per INSERT | None (lock only affects quorum INSERTs to same table) |
| `select_sequential_consistency=1` | Per-query                     | 1 read       | +1-10ms          | None                     | None                                                  |
| `optimize_skip_unused_shards=1`   | Per-query                     | None         | Slight reduction | None                     | None                                                  |
| `load_balancing='in_order'`       | Per-query                     | None         | None             | None                     | None (per-query setting)                              |

| Approach                                 | Guarantee                   | INSERT overhead | SELECT overhead     | Complexity                                            |
| ---------------------------------------- | --------------------------- | --------------- | ------------------- | ----------------------------------------------------- |
| A: Quorum + sequential consistency       | Formal                      | +20-100ms       | +1-10ms (1 ZK read) | High at scale (`insert_quorum_parallel=0` serializes) |
| B: Quorum only                           | 2 replicas only             | +20-100ms       | None                | Low                                                   |
| C: Quorum + SYNC REPLICA                 | Formal                      | +20-100ms       | Sync wait           | Medium (`readonly=2` workaround)                      |
| D: Write to sharded tables               | Inherent                    | None            | None                | High (architectural change)                           |
| E: `in_order` load balancing             | Practical (not formal)      | None            | None                | Low (per-query settings)                              |
| E + quorum: `in_order` + `insert_quorum` | Practical (covers failover) | +20-100ms       | None                | Low (per-query settings, no serialization)            |
