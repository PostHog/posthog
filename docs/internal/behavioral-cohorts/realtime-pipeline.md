# Realtime behavioral cohorts: the streaming pipeline

How we compute behavioral cohort membership incrementally, from live events, instead of recomputing it on a schedule.

---

## 1. The problem

A behavioral cohort is a saved audience defined partly by what people _did_: "performed `$pageview` at least 3 times in the last 30 days AND email contains `@example.com`".

Structurally it is a Boolean tree, stored as JSON on `posthog_cohort.filters`. This document calls that the **filter JSON**. Its leaves are predicates: some behavioral ("did event X, N times, within a window"), some about person properties ("email contains ..."), some references to other cohorts. The tree is what the user edits; the leaves are what the system has to compute.

Cohorts matter beyond the UI because **feature flags can target them**. The flags service evaluates flags without querying ClickHouse, so it needs a cohort's membership available to it locally and fresh. That is the demand this pipeline exists to meet.

The obvious implementation is to periodically re-run each cohort's query. That is what we did first, and it has three costs that grow with adoption rather than with change:

- **Cost scales with `cohorts x persons`, not with what changed.** Every cycle re-evaluates every person for every cohort, even when nothing happened. A person who signed up two years ago and never returned is re-examined forever.
- **Freshness is bounded by the schedule.** Expensive cohorts get moved to a less frequent recompute schedule, so an event that qualifies someone for a flag-gating cohort does not matter until that cohort's next run.
- **"Left because time passed" has no trigger.** "Performed X in the last 7 days" silently expires on day 8. Only a full recompute notices, so the schedule is the freshness floor for exits as well as joins.

The streaming pipeline inverts this: **membership is a value that gets updated by the events that change it**, and nothing else.

### 1.1 Which cohorts this applies to

Only cohorts Django has marked `cohort_type = 'realtime'`. Two Django-side rules disqualify a cohort before the pipeline ever sees it, and they are the first thing to check when a cohort mysteriously does not appear:

- Any cohort using `filterTestAccounts` is forced to the batch path.
- A cohort whose person count exceeds `REALTIME_COHORT_MAX_PERSON_COUNT` (20 million) is not marked realtime.

The pipeline then applies its own exclusions on top (§6).

## 2. The core idea: state per leaf, not per cohort

The batch approach treats the whole tree as the unit of computation. To know membership you evaluate the tree, which means querying that person's event history.

The streaming pipeline decomposes the tree and makes the **leaf** the unit of incremental state:

1. **Stage 1** keeps, per `(team, leaf, person)`, a tiny persistent value that answers that leaf in O(1) with no history lookup. For the pageview leaf that value is a set of per-day counters; for the email leaf it is a boolean. Each event _folds into_ that value: increment today's counter, re-check the predicate. Folding is cheap and local.
2. **Stage 2** composes leaf answers through the cohort's Boolean tree, but **only when a leaf's answer flips**. If a counter goes 5 to 6 under a `>= 3` predicate, the leaf answer did not change, so nothing downstream runs.
3. **The output is deltas, not snapshots.** On the live path a `CohortMembershipChange {team_id, cohort_id, person_id, status: entered|left}` message is produced only when composed membership actually flips. (Backfill adds one snapshot mode on top of this; see [backfill.md](./backfill.md) §5.8.)

Two things fall out of this:

- **Work is proportional to relevant change.** An event costs evaluation only for the leaves it could possibly affect. A person who sends no events costs nothing, until a time window expires (§10.1).
- **All of one person's state must live in one place.** Folding is a read-modify-write of that person's leaf states on every event. Those states have to be co-located with the stream that mutates them, which is why the whole system is built around Kafka partition affinity and an embedded store rather than a shared database.

### 2.1 Condition hashes and leaf state keys

These two identifiers are not the same thing, and the difference is load-bearing.

- A **condition hash** identifies the leaf's _matching predicate_. Django compiles the predicate to bytecode for **HogVM**, our stack machine for filter expressions, and the condition hash is the first 16 hex characters of a SHA-256 over that compiled bytecode. It answers "does this event match?" and nothing else. It does **not** include the window or the threshold.
- A **leaf state key** (LSK) is the state identity: condition hash, the behavioral value (`performed_event` vs `performed_event_multiple`), the window, the operator and threshold, and explicit date bounds (a leaf can pin an absolute start and end date instead of a rolling window). It answers "which stored value does this leaf read?". It deliberately excludes negation, because state is invariant to it: "did X" and "did not do X" read the same counter and disagree only at evaluation time.

So one condition hash can fan out to several leaf state keys. "Performed `$signup` in the last 7 days" and "performed `$signup` at least 3 times in the last 30 days" share a predicate, so an event is matched once and applied to both. Ten cohorts that all say "performed `$signup` in the last 30 days" share a single stored value and a single evaluation. Deduplication is structural, not an optimization pass.

One consequence worth carrying around: because the hash digests _compiled bytecode_, any change to the bytecode compiler rotates every condition hash at once and cold-starts all Stage 1 state fleet-wide. Treat compiler changes as a data migration.

## 3. Topology

```text
                   clickhouse_events_json    the event firehose (Kafka topic), keyed by event uuid
                             |
                  +----------v-----------+
                  | cohort-event-shuffler |   stateless, horizontally scaled
                  |    gate and re-key    |   drops teams with no realtime cohorts
                  +----------+-----------+
                             |
   inputs to the processor:  v
     cohort_stream_events         64p, key = "{team}:{person}"   the hot path
     person_merge_events          64p, keyed by the merged-away person      (§11)
     cohort_merge_state_transfer  64p, keyed by the surviving person        (§11)
     cohort_cascade_events        64p, keyed by the affected person         (§10.3)
     cohort_stream_seed_events    64p, backfill tiles                       (backfill.md)
                             |
                  +----------v-------------+
                  | cohort-stream-processor |  stateful, one worker per owned partition
                  |    Stage 1 + Stage 2    |  RocksDB on a persistent volume
                  +----------+-------------+
                             |
   outputs:                  v
     cohort_membership_changed*   the product output: entered / left deltas
     cohort_merge_state_transfer  loops back in as an input
     cohort_cascade_events        loops back in as an input
     cohort_reconcile_markers     backfill completion markers (produce only)
     cohort_stream_events         loops back in: post-merge re-keys (§11)
```

The five input topics are **co-partitioned at 64 partitions with the same key function**, `murmur2` over the string `"{team_id}:{person_id}"`. That co-partitioning is the invariant the whole design rests on: **everything that can mutate person P's state arrives on the same partition number, and exactly one worker owns that partition.** No locks, no cross-worker coordination, and a read always sees the worker's own prior writes.

At boot the processor fetches broker metadata and refuses to start on a mismatch, but the checks are not uniform: `cohort_stream_events` is compared to `COHORT_PARTITION_COUNT` (default 64), the merge and transfer topics are compared to the _observed_ events count, the cascade and seed topics are checked only when their gates are on, `cohort_reconcile_markers` is checked for existence only (nothing co-partitions with it), and the output topic is not checked at all.

The partition count is fixed rather than derived because the merge protocol has to reproduce Kafka's producer-side partitioning **client-side**, to compute which worker owns a given person. The partitioner is `murmur2_random`, `(murmur2(key) & 0x7fffffff) % partitions`, which is the Kafka-Java and Node default rather than the CRC32 default of librdkafka (the C client the Rust services use). It is pinned by cross-language fixtures on both the Rust and Node sides, because the Node ingestion service produces merge events into the same scheme (§11).

Cohort _definitions_ do not travel through Kafka. Both the shuffler and the processor poll Postgres directly (§6).

The output topic name is config (`COHORT_MEMBERSHIP_CHANGED_TOPIC`) and defaults to `cohort_membership_changed_shadow`, the shadow topic. Pointing it at the topic production consumers read is a config change, not a code change.

## 4. The shuffler: gate cheaply, re-key for affinity

`rust/cohort-event-shuffler` is a small stateless service with one job: consume the firehose (keyed by event UUID, so one person's events are scattered across every partition) and re-publish the relevant ones keyed by `(team, person)`.

**Why a separate service.** The processor needs per-person affinity, and the firehose is orders of magnitude larger than the subset that matters. Making the stateful service consume everything and re-shuffle internally would put the entire firehose through the expensive tier. A cheap stateless tier does the re-key and, more importantly, the _filtering_: only teams that actually have realtime cohorts survive.

**The two-phase parse.** Fully deserializing every event just to discard most of them would make JSON parsing the dominant cost, because each event carries multi-KB `properties` and `person_properties` blobs. So decoding happens twice over the same byte slice (`consumer.rs`):

- _Phase 1_ deserializes into a struct with only `{team_id: i32, person_id: Option<IgnoredAny>}`. `serde::de::IgnoredAny` walks and discards every other field without unescaping or allocating, so the fat blobs are never materialized.
- _Gate:_ drop if `person_id` is absent (there is nothing to key state by), skip if `team_id` is not in the team index.
- _Phase 2_ re-parses the same bytes into the full event, only for survivors. Both phases read the same payload, so the forwarded envelope is byte-identical to what a single-parse implementation would emit, which keeps the optimization invisible to everything downstream.

**The team index** (`filter_team_index.rs`) is an `ArcSwap<HashSet<i32>>` refreshed every 300s with up to 60s of jitter, so replicas do not all hit Postgres in the same second. The query is `SELECT DISTINCT team_id FROM posthog_cohort WHERE cohort_type = 'realtime' AND deleted = false AND filters IS NOT NULL`, intersected in memory with `REALTIME_COHORT_TEAM_ALLOWLIST`. Reads are lock-free. Staleness is fine because the processor re-checks against its own catalog (§6) anyway. The service refuses to consume at all until the first successful load, so a cold start cannot advance offsets past events it should have forwarded.

**The output message** (`event.rs`) keeps only what evaluation needs: `team_id`, `person_id`, `distinct_id`, `uuid`, `event`, `timestamp`, `properties`, `person_properties`, `elements_chain`, plus `source_partition` and `source_offset`. Those last two are the _firehose_ coordinates, and they are what makes downstream folding idempotent under replay (§13).

**The offset ledger.** A naive loop of consume, produce, await ack, commit would throttle intake to the producer's ack latency. The ledger (`ledger.rs`) decouples them: consumption runs ahead of acks up to `MAX_INFLIGHT_FORWARDS` (default 4000), and per source partition it tracks `committable = in_flight.is_empty() ? high_watermark + 1 : min(in_flight)`. Dropped and skipped events settle immediately and lift the watermark without blocking. A commit tick every 5s commits what is committable, so a crash replays at most a few seconds of already-forwarded events.

Semantics into `cohort_stream_events` are therefore **at-least-once**. One sharp edge: a produce that fails terminally (for example `MessageSizeTooLarge`) is settled as _abandoned_, a deliberate and counted data-loss path (`shuffler_events_abandoned_total`) that keeps one poison message from wedging the pipeline.

## 5. The processor runtime: partitions, workers, offsets

`rust/cohort-stream-processor` is one process built around **single-threaded logical workers, one per owned Kafka partition**, on a shared multi-threaded tokio runtime.

**One consumer, one router, N workers.** A single `StreamConsumer` reads `cohort_stream_events`. Its consumer group uses cooperative-sticky assignment (a rebalance moves only the partitions that have to move) and manual offset commits. It also uses static membership, so a restart does not trigger a full group rebalance, but only when `POD_NAME` or `HOSTNAME` is set; outside Kubernetes the group is dynamic. A consume loop batches messages and hands them to a `PartitionRouter`, which fans sub-batches into per-partition bounded channels. Each channel is drained by a worker task that owns everything for its partition: its slice of the store, its eviction queue, its GC cursors, and the ordering guarantee. Because `(team, person)` hashes to exactly one partition, per-person processing is serial by construction.

Routing is by Kafka partition identity, not by re-hashing. The shuffler already keyed by `(team, person)`, so the Kafka partition number _is_ the worker id. Workers are spawned lazily on the first batch delivered to an owned partition.

Everything the worker can be handed is a `ShuffleMessage`: a live `Event`, a `Sweep` tick, a `Merge` or `Transfer`, a `Cascade`, a `Seed` tile, or a maintenance tick (`RedrivePendingTransfers`, `MergeCfGc`, `ReconcileDrain`; "Cf" is a RocksDB column family, §7.3). Putting them on one channel is what serializes eviction and backfill against event processing instead of racing them.

**Followers, not independent subscribers.** The merge, transfer, cascade, and seed consumers never call `subscribe()` and never take part in the rebalance protocol. They **mirror** the events consumer's assignment via `incremental_assign` / `incremental_unassign`, while committing their own progress to their own consumer groups. The events group is the single source of truth for ownership, so every stream for partition N funnels into worker N. Only two of the four exist by default: the cascade and seed followers are constructed only when their gates are on.

**Backpressure that degrades into lag, not crashes.** The failure a stream processor must avoid is one slow partition stalling the shared consume loop: if dispatch blocks, polling stops, the Kubernetes liveness probe stops passing, and the process is killed while healthy work sits in other partitions. So dispatch is non-blocking end to end. Each partition has an intake budget (`PARTITION_INTAKE_MAX_EVENTS`, default 1024) on top of channel slots; admission is `try_admit` and a batch that does not fit is never awaited. Rejected batches go to a **holdover buffer**, and a pauser task calls `consumer.pause()` on exactly those partitions. Overload therefore shows up as per-partition Kafka lag, which self-heals when load drops and is visible on a dashboard.

**Four commit floors per partition.** `dispatched_offset` (raised after a batch is routed, for what actually landed; no commit may pass it), `processed_offset` (raised by the worker after a sub-batch is processed _and its output produces are acknowledged_), an optional `held_offset` (a sticky floor pinned when a produce or a store write fails, forcing redelivery from the failed message), and a set of `deferred` offsets (used by the backfill reconcile job to hold its own offset until a long scan completes). The committable offset is the minimum of whichever are present.

A dedicated task commits the events group every 5s. The four followers commit inline on a deadline inside their own consume loops, so a stalled follower stalls only its own commits, which is exactly the coupling the separate events-commit task exists to avoid. The property that matters, and the reason commits are manual: **an offset only advances past an event once that event's membership output has been acknowledged**, and failures hold the floor rather than skipping.

## 6. The catalog: from filter JSON to something evaluable

A catalog manager polls Postgres every 300s with up to 60s of jitter. The query is fleet-wide, covering every realtime cohort joined to `posthog_team` for the IANA timezone; the team allowlist is applied in memory afterwards, so every pod runs a full `posthog_cohort` scan on that cadence. The result is parsed, indexed, and swapped in atomically via `ArcSwap`; the hot path takes a lock-free snapshot per event. A failed refresh keeps the previous snapshot, because a stale catalog beats no catalog.

Each catalog carries a generation number and a hash of its contents. A refresh whose contents are identical reuses the generation, so anything cached against that generation stays valid instead of being invalidated fleet-wide every five minutes. The person record's `catalog_fingerprint` (§7.4) is the main beneficiary.

**Leaf classification** walks the filter JSON and assigns every leaf a state variant based on its `type` and `value` fields:

| Leaf                                                            | Requires                  | Stage 1 state variant                                       |
| --------------------------------------------------------------- | ------------------------- | ----------------------------------------------------------- |
| `behavioral` / `performed_event`                                | condition hash + bytecode | `BehavioralSingle` (a bit plus timestamps)                  |
| `behavioral` / `performed_event_multiple`, window 1 to 180 days | same                      | `BehavioralDailyBuckets` (a dense array, one count per day) |
| `behavioral` / `performed_event_multiple`, window over 180 days | same                      | `BehavioralCompressedHistory` (sparse `(day, count)` pairs) |
| `person` (property predicate)                                   | condition hash + bytecode | `PersonProperty`, stored in the person record (§7.4)        |
| `cohort` (reference to another cohort)                          | target id                 | no state; resolved through Stage 2 and cascades (§10.3)     |

The 180-day split is a storage trade: a dense array costs a slot per day whether or not anything happened, which is cheap for a month and wasteful for a year, so long windows switch to the sparse form.

A leaf that cannot be supported is dropped, incrementing a counter labeled with the reason, and dropping a leaf disqualifies the whole cohort rather than silently changing its meaning. Reasons include missing bytecode, an action id rather than an event name as the behavioral key (actions are saved event matchers, and the pipeline does not resolve them), a sub-day window on `performed_event_multiple` (a single `performed_event` with an hour or minute window _is_ supported, with a second-granular eviction deadline), and any leaf type the classifier does not recognize. Only `behavioral`, `person`, and `cohort` are recognized, so a `person_metadata` leaf disqualifies its cohort even though Django's flag-compatibility gate ([backfill.md](./backfill.md) §1) counts it as a person filter.

**Eligibility classes.** Each cohort is classified once per catalog build, in this precedence order: a dropped leaf anywhere, then an empty group anywhere, then a negated root, then a cohort reference. What survives is:

- `SingleLeaf`: exactly one leaf that owns Stage 1 state. The leaf's answer _is_ the membership; no composition needed.
- `Stage2Composable`: two or more state-owning leaves, no dropped leaves, no cohort references, no negation at the root.
- `Stage2ComposableRef`: contains cohort references whose positive targets are resolvable and cycle-free. Cycles are found with Tarjan's strongly-connected-components algorithm over the reference graph, and classification runs in reverse topological order so referenced cohorts are classified before their referrers.
- `Excluded(reason)`: everything else. Excluded cohorts produce no output at all.

A negated _root_ is excluded because it inverts membership into "everyone who does not match", and a delta pipeline can only speak about people it has state for; it has no way to enumerate the complement. Note the check is broader than it sounds: for an `OR` root, _any_ negated child counts, so `OR(A, NOT B)` is excluded too.

**The reverse index** is the structure the hot path actually reads, built once per refresh:

- `behavioral_by_event_name`: event name to condition hashes, built from each behavioral leaf's event key in the filter JSON. This is the **event-name gate** (`COHORT_EVENT_NAME_GATING_ENABLED`, default on). An incoming `$pageview` only evaluates conditions whose leaf names `$pageview`; every other behavioral condition in the team is never touched.
- `by_condition_to_lsk` and `by_condition_to_bytecode`: condition hash to leaf state keys, and to shared bytecode (one `Arc` per hash regardless of how many cohorts use it).
- `by_lsk_to_single_leaf_cohorts` and `by_lsk_to_composable_cohorts`: leaf state key to the cohorts whose membership can change when that leaf flips. This is what makes Stage 2 targeted.
- `person_conditions_ordered`: the sorted list of the team's person-property condition hashes, plus a `CatalogFingerprint` over it, used by the person record's freshness check (§7.4).

**What a cohort edit does.** Django writes new filter JSON with new condition hashes for changed conditions; within one refresh cycle the catalog swaps. New condition hashes mean new, empty Stage 1 state, because state is keyed by condition semantics rather than by cohort id. So an edited condition warms up from scratch unless it is backfilled, and the team's catalog fingerprint changes, which invalidates every person record's cached person-property evaluation on that person's next event.

## 7. The store: why RocksDB, and why embedded

### 7.1 Why embedded

The hot path is a read-modify-write of a handful of small records per event, thousands of times a second. A network database would put a round trip inside that loop and a shared lock domain underneath it.

An embedded log-structured merge-tree (LSM) store gives the worker microsecond point reads on cache hits, atomic multi-column-family write batches, and prefix iteration, with no network and no contention, because each partition worker is the only writer for its key range.

The trade normally made against embedded stores is durability, and it does not bite here: **Kafka is the replication log.** The store can always be rebuilt by replaying the input topics, so RocksDB is a local materialization rather than the system of record. Durability is layered on separately (§12).

### 7.2 The keyspace: everything a person has, in one contiguous slice

Every partitioned key starts with the same 26-byte **person prefix**:

```text
PersonPrefix (26 bytes)          BehavioralKey (42 bytes)         Stage2Key
[0..2)   partition_id  u16 BE    [0..26)  PersonPrefix            (partition, team, cohort, person)
[2..10)  team_id       u64 BE    [26..42) LeafStateKey (16 bytes)
[10..26) person_id     uuid
```

RocksDB sorts keys lexicographically, so big-endian fixed-width encoding gives two properties. Partition N's rows form one contiguous range, which makes a partition wipe a single `delete_range`. And within that range, **all of person P's behavioral leaf states are physically adjacent on disk**, so in practice they land in the same one or two blocks. The person record uses the bare 26-byte prefix as its key, so it sits right next to the same person's leaf rows.

To see why that matters, consider the natural alternative of keying state by `(condition, person)`. A team with hundreds of conditions would scatter one person's states across hundreds of regions of the store, so processing one event would issue hundreds of point reads, each landing on a different block. The working set per event would then be proportional to _store size_, since every block is equally likely to be cold, and throughput would collapse as the store outgrew RAM. Clustering by person collapses an event's working set to roughly one to three adjacent blocks **regardless of store size**, which is what decouples throughput from store growth (§9 has the measurement).

The store stamps `STORE_SCHEMA_VERSION` (currently 3) into `cf_meta` at first open, and a mismatched stamp fails hard at boot unless `COHORT_WIPE_ON_SCHEMA_MISMATCH=true`. There is deliberately no in-place migration machinery: the store is rebuildable from Kafka, so wipe-and-refold is the schema-upgrade strategy.

### 7.3 Column families

A **column family** is an independently configured keyspace inside one RocksDB instance. They share a write-ahead log and can be written atomically together, which is what lets an event's behavioral and person-record updates commit as one unit.

Eight of them, sharing one block cache:

| CF                        | Key                                         | Holds                                                                    |
| ------------------------- | ------------------------------------------- | ------------------------------------------------------------------------ |
| `cf_behavioral`           | person prefix + 16-byte leaf key            | Stage 1 behavioral state, one row per `(person, leaf)`                   |
| `cf_person_records`       | person prefix                               | one record per person: property-evaluation memo plus replay dedup (§7.4) |
| `cf_stage2`               | (partition, team, cohort, person)           | composed membership bit per `(cohort, person)`                           |
| `cf_merge_drains_applied` | (partition, team, old person, merge coords) | merge phase 1 idempotence markers                                        |
| `cf_pending_transfers`    | (partition, team, old person)               | outbox for cross-partition merge transfers                               |
| `cf_merge_applied`        | (partition, team, new person, merge coords) | merge phase 2 idempotence markers                                        |
| `cf_merge_tombstones`     | (partition, team, person)                   | "P was merged into Q" redirects for late events                          |
| `cf_meta`                 | ASCII literals                              | store-wide metadata, for example the schema stamp                        |

Every column family except `cf_meta` is partition-prefixed, and the "is this partitioned?" question is an exhaustive match with no wildcard, so adding a family forces you to answer it. A range delete over a non-partitioned family would wipe store-wide state.

`cf_stage2` carries two extra namespaces alongside membership rows: dirty markers used by the backfill reconcile scan ([backfill.md](./backfill.md) §6.4) and transferred register rows (§10.2). Both are keyed as the partition id followed by 32 bytes of `0xFF` and then a low discriminant byte, so they sort after every real membership key while staying inside that partition's range even in the last partition.

### 7.4 The person record: all person-property state in one value

Person-property conditions have a shape that punishes naive storage. Teams have hundreds of them, they all evaluate against the same `person_properties` blob, and most events carry that blob. Stored one row per `(condition, person)`, every event would rewrite hundreds of rows.

Instead there is **one binary record per person** holding:

- `props_fingerprint`: 128 bits of SHA-256 over the raw `person_properties` JSON of the last evaluated event.
- `catalog_fingerprint`: 128 bits of SHA-256 over the team's sorted person-property condition hashes.
- `matched`: the sorted set of condition hashes currently true for this person, which is the complete person-property answer in one value.
- `stamp` (event timestamp plus offset, a last-write-wins key so out-of-order events cannot regress state), `last_seen_ms` (read by the TTL compaction filter), `applied_offsets` (per source partition replay high-water marks), and `redirect_dedup` (per merged-away ancestor offsets, §11).

The record is both a **storage collapse** (hundreds of rows into one) and an **evaluation memo**: if an event's props fingerprint and the catalog fingerprint both match what is stored, the entire person-property evaluation is skipped. That is why the pipeline averages about one write batch per event rather than hundreds of writes.

### 7.5 Reads and writes per event, exactly

The event path does **one batched read and one atomic write batch** per event:

1. _Plan_: parse ids and timestamp, take a catalog snapshot, consult the reverse index, and compute the exact key set. That is one behavioral key per surviving condition (usually 0 to 2 thanks to the event-name gate) plus the person record key if the team has person conditions.
2. _Snapshot read_: one `multi_get` covering all of those keys across both column families. Because they share the person prefix, they hit the same one or two cached blocks.
3. _Fold_: pure in-memory mutation producing new state values and any leaf transitions.
4. _Write_: one `StagedBatch` applied as a single atomic `WriteBatch`, so the person record update and the behavioral updates commit together or not at all.

### 7.6 Cache, bloom filters, compaction

- **Block cache**: one shared LRU across all column families (`COHORT_BLOCK_CACHE_BYTES`). With `COHORT_TUNED_BLOCK_OPTIONS_ENABLED` on (the default), index and filter blocks are cached _inside_ it, with level-0 index and filter blocks pinned and two-level partitioned indexes, so metadata cannot be evicted wholesale by data churn and a point read costs at most one data-block fetch.
- **Bloom filters, two kinds.** Every CF gets a 10-bits-per-key whole-key bloom unconditionally, so a `get` for a key that does not exist (the common case: most persons have no prior state for a given leaf) is answered "definitely absent" from the filter block without touching a data block. `cf_behavioral` additionally gets a 26-byte fixed-prefix extractor plus a memtable prefix bloom, so a prefix seek for "everything this person has" (used by merges and drains) can skip whole SSTs, the immutable files an LSM store compacts into.
- **Compact-on-deletion**: eviction sweeps and merge drains produce tombstone bursts, so a deletion collector marks tombstone-heavy SSTs for compaction instead of letting dead rows accumulate as read amplification.
- **TTL compaction filter**, on `cf_person_records` only (`COHORT_PERSON_RECORD_TTL_DAYS`): during compaction, records whose `last_seen_ms` is older than the TTL are dropped, so dormant persons age out with no foreground work. `cf_behavioral` deliberately does _not_ get one, because its rows are owned by the eviction sweep, which must _observe_ expiry in order to emit `left` (§10.1).
- **Writes** use an async write-ahead log, with an explicit `flush_wal(true)` fsync on the offset-commit cadence so the durability floor tracks commits rather than every write (§12). Atomic flush is on, so column families cannot flush independently and leave one half of an event's write batch durable without the other.

### 7.7 Keeping blocking I/O off the async runtime

Some reads miss to disk, and a synchronous RocksDB call parks an entire tokio runtime thread for the duration. On a pod with a handful of runtime threads, a burst of cold reads can park all of them, and then the consume loop, offset commits, and health signals starve behind disk I/O even though the CPU is idle.

The `StoreHandle` facade routes store I/O through `spawn_blocking` with two semaphore lanes: event-path reads (`COHORT_STORE_EVENT_READ_PERMITS`, default 16) and maintenance reads for sweeps, GC, and backfill application (`COHORT_STORE_MAINTENANCE_PERMITS`, default 6). A burst of maintenance I/O therefore cannot starve live events. `StagedBatch` exists so a fully owned write set can cross into the blocking pool.

How much of this is active is itself a knob: `COHORT_STORE_OFFLOAD_MODE` is `all` by default, but `maintenance` keeps event-lane reads and most writes inline, and `off` runs everything inline. Only `all` gives the "no store call parks the runtime" property, and `off` is the kill switch to reach for if the blocking pool itself misbehaves.

## 8. The life of an event

### 8.1 A behavioral event

1. **Plan.** Parse `person_id` and timestamp (either failing skips the event with a counted reason). The event-name gate looks up `behavioral_by_event_name["$pageview"]`; say two conditions survive. Their bytecode runs against a _globals_ object, the variable environment HogVM evaluates against, built from the event's fields. Say one matches.
2. **Snapshot read.** One `multi_get` for that condition's behavioral key plus the person record key.
3. **Fold.** For `BehavioralDailyBuckets`: slide the window forward to the event's calendar day _in the team's timezone_, increment that day's bucket, re-evaluate the predicate over the bucket sum. If the count crossed the threshold, that is a **leaf transition**. Compute the new eviction deadline and schedule it (§10.1).
4. **Person side.** If the event carries `person_properties` and the team has person conditions, the person record path runs too, usually short-circuiting on the fingerprint memo.
5. **Stage 1 commit.** Behavioral state and person record commit as one atomic write batch.
6. **Stage 2.** For each leaf transition, look up `by_lsk_to_composable_cohorts`. For each affected cohort, read that cohort's full leaf set, fold the Boolean tree, and diff against the stored `cf_stage2` bit. Cohorts whose bit did not flip produce nothing. Single-leaf cohorts skip composition entirely.
7. **Emit.** Buffered membership changes are produced at the end of the sub-batch; the worker marks the offset processed only after the produce is acknowledged.

### 8.2 A person-property change

Ingestion rewrites the person, and subsequent events carry the new `person_properties`. There is no separate "person changed" topic: property changes ride on events.

The first event after the change has a mismatching props fingerprint, so person conditions are evaluated: globals are built once (one JSON parse), every person-property condition hash in the team's catalog runs through a reused evaluator, and the resulting matched set is diffed against the stored one. Each flipped condition becomes a leaf transition; the new record (new fingerprint, new matched set, advanced stamp) is staged. Every _subsequent_ event from this person matches the fingerprint and skips the whole path.

### 8.3 An event that matches nothing

The overwhelmingly common case, and the cheapest. Wrong team means dropped at the shuffler in phase 1 and never re-keyed. An allowlisted team whose event name matches no behavioral condition, with fingerprints matching, yields no behavioral applies and no person evaluation, so the event costs zero or one point read.

### 8.4 An event for a merged-away person

Before the normal path, the worker consults `cf_merge_tombstones`. If this person was merged into Q, the event is redirected and folded as if it belonged to Q (same partition), or re-produced onto Q's partition (cross-partition), so late events still land on the surviving person's state (§11).

## 9. Why this stays cheap at scale

There are **four nested gates**, each cutting the work the next one sees, and none of them ever enumerates cohorts to ask "who might care?".

1. **Team gate (shuffler).** Most of the firehose belongs to teams with no realtime cohorts and is dropped after a two-field parse. Cost: near zero.
2. **Event-name gate (reverse index).** A behavioral condition can only be affected by events whose name its leaf selects. This turns "which of this team's hundreds of behavioral conditions could a `$pageview` touch?" into a hash lookup returning a handful.
3. **Fingerprint memo (person record).** Person-property conditions can only be affected when the properties actually changed. One 128-bit comparison skips the entire person-property machinery for every event where they did not. This is what makes it safe for person conditions to have no per-event-name gate.
4. **Flip-driven composition (leaf to cohort index).** When a leaf does flip, `by_lsk_to_composable_cohorts` names exactly the cohorts whose tree contains that condition. A team with 500 cohorts where the flipped condition appears in 2 of them does Stage 2 work for 2. An event that flips no leaf does no Stage 2 work at all.

On top of those, condition-hash-keyed state means N cohorts sharing a predicate cost one fold and one evaluation, not N.

So an email change costs: one person-record read, one JSON parse, one bytecode run per person condition in the team's catalog, a set diff, and tree folds only for the cohorts containing the conditions that flipped. No cohort scan, no person scan, no event-history query, ever.

**Where this stops being cheap.** Within the person-property machinery, granularity is the team's _person-condition set_, not the single property key. There is no `property_key -> conditions` index, so a genuine property change re-evaluates all of the team's person conditions for that person. This is a deliberate trade: evaluation is pure CPU on data already in hand, the matched set is one value, and the fingerprint memo makes it rare. A property-key index is the known next lever if a team with very many person conditions ever hurts.

**Measured shape.** In production a single pod sustains event rates on the order of a thousand per second, with p99 event latency in the tens of milliseconds, at roughly 5 store reads, 1 write batch, and a few CPU-milliseconds per event. Those per-event costs stayed flat across a load ramp of more than 10x, which is the property that matters: cost tracks change, not size.

## 10. Time, eviction, and cascades

### 10.1 Leaving a cohort with no event to trigger it

Half of behavioral-cohort semantics is time passing. "Performed X in the last 7 days" must go false on day 8 with no triggering event. Batch recomputation gets this for free; a streaming system needs an explicit mechanism.

Every behavioral Stage 1 fold computes, alongside the new state, an **eviction deadline**: a conservative bound on the earliest future instant at which this state's answer could change through time alone. For daily buckets that is when the _oldest non-zero_ bucket leaves the window, which ignores the threshold, so a state with several contributing days wakes up early, finds no transition, and reschedules. For a single-event condition with a day window it is midnight of `day(event) + days + 1` in the team timezone; with a sub-day window it is the exact instant. Two classes are never scheduled: permanent states, and leaves pinned to an absolute date range, whose membership cannot age out. Person-property leaves have no deadline at all, because they have no window.

Deadlines feed a per-partition **eviction queue**, a `BTreeMap<(deadline, seq), key>` paired with a reverse map. It is deliberately not a lazy-deletion heap. Deadlines move _backwards_ as well as forwards, because a late event can add a bucket older than the current oldest. A heap would leave the superseded far-future entry in place until its stale deadline surfaced, up to the window length, so heap size would grow with total reschedules rather than with live keys. The `BTreeMap` plus reverse index removes the superseded entry precisely in O(log n) in either direction.

A sweep scheduler ticks every `SWEEP_INTERVAL_MS` (30s), with the first eviction pass delayed by `COHORT_FIRST_EVICTION_SWEEP_DELAY_MS` (120s) so a fresh pod's read burst does not stack on its boot backlog. That delay has an operational edge: a pod restarting more often than 120s never evicts at all, and worst-case post-restart `left` lag is the safety margin plus the delay plus one interval.

Each tick dispatches a sweep message to every owned partition through the same channel as events, so eviction is serialized with event processing and cannot race it. The cutoff is `now - SWEEP_SAFETY_MARGIN_MS` (5 minutes), which absorbs the one place timezone conversion is ambiguous: converting a calendar day back to an instant across a DST transition. That back-dated instant is also used as the fold's "now" and as the timestamp on anything the sweep writes.

Each partition pops at most 10,000 due keys per pass, so a 64-partition pod can pop up to 640,000 in one tick. Daily-bucket deadlines cluster on timezone midnight, so a large team's whole wave can come due at once; the cap bounds one partition's read, produce, write, and Stage 2 work so live events on that partition do not queue behind a giant sweep. Leftovers stay scheduled and drain on the next tick.

The callback re-reads state on the maintenance I/O lane in chunks, then runs a **pure** eviction fold: drop aged-out days, recompute the predicate, return a transition plus write-or-delete. The two legs of a sweep have opposite delivery postures, which is worth knowing when you are reasoning about a missing `left`:

- **Stage 1 leg**: membership changes are produced _before_ state is written. A produce error reschedules the whole popped set and writes nothing, so the pass replays against still-un-evicted state. A write error after a successful produce also reschedules, so that transition can re-emit next pass: at-least-once.
- **Stage 2 leg**: `cf_stage2` is committed first and produced afterwards, so a produce failure drops the change. At-most-once, same as the event path.

Fully-expired state is deleted, which is why `cf_behavioral` has no TTL filter: expiry has to be observed to be emitted.

The queue is in-memory, so it has to be rebuilt after a restart. That rebuild (a paginated scan of `cf_behavioral`) runs only when `DURABLE_RESTORE_ENABLED` is on. At defaults the store is wiped on boot anyway, so there is nothing to rebuild and a dormant person's pending `left` is simply lost until the state is rebuilt from the stream or a backfill.

### 10.2 Stage 2 composition

For a leaf transition on person P, the evaluator reads _all_ of the affected cohort's leaf states (the behavioral ones in one `multi_get`, the person-property ones from a single person-record read), folds the AND/OR tree, and compares against the stored bit in `cf_stage2`. Absent rows mean "never a member".

Only flips are **emitted**. Writes are slightly broader: a row whose membership did not change is still rewritten if it was carrying a merge-transferred ownership marker that this evaluation now claims.

Behavioral leaves are read from `cf_behavioral`; **person-property leaves are answered from the person record, never from `cf_behavioral`**. A person-property state reaching the behavioral resolver would be a desync, so it is counted and read as a non-member. The failure mode is loud and never a silent membership.

Negation is per-leaf, an XOR against the leaf's `negated` flag rather than a node type, so a negated absent leaf reads true. Root-level negation is excluded upstream by the eligibility classifier (§6).

Single-leaf cohorts skip composition entirely and write a **register row** straight from leaf state, including an explicit `in_cohort=false`, so that a later full scan of `cf_stage2` sees every person whose leaf has ever transitioned. That completeness is what the backfill reconcile snapshot depends on.

Stage 2's own delivery posture is at-most-once (state commits before the produce). A dropped _composed_ flip self-heals on that person's **next leaf transition**, because Stage 2 re-derives the whole cohort from stored leaf state whenever any of its leaves flips. Events that flip nothing do not repair it, and a dropped _single-leaf_ change has no self-heal at all. That is why the reconcile snapshot exists.

### 10.3 Cohort cascades

Cohort A can reference cohort B ("person is in cohort B AND ..."), so a membership flip of B must re-evaluate A. This is off by default (`COHORT_CASCADE_ENABLED`) because it needs its own topic and interacts with the durability gates (§12), so it is enabled per environment rather than shipped on. With it off, every reference-bearing cohort is `Excluded` and produces nothing.

**Resolution depth inside one evaluation is exactly 1.** A referenced cohort's answer is read from storage: its `cf_stage2` bit, or the leaf bit for a single-leaf target, resolved through the same comparator its own leaves use. There is no recursive descent. Negated references read absent-as-true, which is also why a purely negated reference never blocks eligibility.

Transitive propagation is delegated to Kafka. With cascade on, a worker produces a `CascadeMessage` to `cohort_cascade_events` for **every** membership change it emits, keyed by `(team, person)` so it lands back on that person's own partition worker. It does not consult the reference graph first, so a flip on a cohort nothing references still costs a Kafka round trip. The lookup happens on the consuming side, where the handler resolves the flipped cohort's referrers, re-evaluates each, and if one flips emits membership changes _and further cascades_.

The cascade path deliberately inverts the event path's commit order: it **produces before writing state**. The referrer's new `cf_stage2` bit commits only after both the membership produce and the onward cascade produce are acknowledged, so any failure holds the offset without writing and replay re-detects the still-old bit. That is the ordering the event path does not yet have (§13).

Three independent guards bound the loop:

1. **Load time.** Tarjan's SCC over the reference graph, including self-loops, marks cyclic cohorts `Excluded(CycleDetected)`.
2. **Consumer side.** A referrer is re-evaluated only if its eligibility class actually writes `cf_stage2`, which is what keeps an excluded cycle member from re-entering the chain.
3. **Runtime.** A depth cap (default 8) checked before the chain, then a `cascade_chain` membership check. The referrer list is truncated at a fan-out cap (default 1000) _before_ the eligibility filter runs, so the cap bounds referrers considered rather than referrers re-evaluated.

Ordering between hops is not guaranteed. Each hop is an independent message on a person-keyed partition, so a dependent's re-evaluation reads whatever bit is currently stored. A stale read self-heals on the next flip or on the referrer's next event.

**Static cohorts do not exist in this pipeline.** A static cohort is a fixed list of persons rather than a filter tree, and the catalog query selects `cohort_type = 'realtime'` only, so it is simply absent. A positive reference to one is therefore unresolvable and excludes the referrer; a negated-only reference resolves as absent, which reads true.

### 10.4 Stage 2 GC

When a cohort is deleted or reclassified out of the pipeline, its `cf_stage2` rows become orphans. An hourly scan deletes rows whose cohort is absent from the current catalog's **membership-registering** set, which is single-leaf cohorts plus both composable classes. That set is deliberately wider than the composable-only set: single-leaf register rows are live membership, and treating them as orphans would delete exactly the rows the backfill reconcile snapshot scans.

The scan uses a resume cursor and a per-tick key cap. It is deliberately catalog-based rather than timestamp-based (a dormant member's row is old but must live) and fail-closed: it never runs before the first successful catalog load and never runs against an empty snapshot, so a transient refresh failure cannot mass-delete state.

## 11. Person merges

Ingestion merges two person records when it learns they are the same human, typically when an anonymous visitor later identifies. This is routine, not exceptional.

When person `P_old` merges into `P_new`, the pipeline has to combine their behavioral histories, or a "performed X at least 3 times" cohort under-counts and every subsequent answer for the merged person is wrong.

Merges are the hardest part of the design, because `P_old` and `P_new` usually live on **different partitions** (their ids hash differently), which breaks the one-owner invariant everything else relies on. The protocol is a two-phase state hand-off over Kafka:

- **Trigger.** The Node ingestion service (`plugin-server`) produces to `person_merge_events` keyed by _`P_old`_, so the message arrives at the worker that owns `P_old`'s state. The producer is gated three ways (`PERSON_MERGE_EVENTS_ENABLED`, a non-empty topic name, and `PERSON_MERGE_EVENTS_TEAM_ALLOWLIST`) and computes the partition explicitly with Kafka-Java murmur2, because librdkafka's default partitioner would route to the wrong worker. Emission is detached from the ingestion ack chain, deliberately, so that a shadow consumer can never slow or fail live ingestion. The cost is that merge delivery is at-most-once for now.
- **Phase 1, drain.** The worker prefix-scans `P_old`'s 26-byte slice, packages its leaf states plus the person record's dedup carrier, deletes `P_old`'s rows, and writes a **tombstone** (`P_old -> P_new`) plus an idempotence marker. A leaf whose stored value fails to decode is counted and dropped rather than transferred, while the range delete is unconditional, so a corrupt leaf is lost at the merge. Before choosing a route the drain resolves `P_new` through its own local tombstone chain, so a merge into an already-merged person targets the survivor directly. If that target is co-resident on the same partition, drain and apply happen in one atomic batch with no Kafka hop. Otherwise the package is staged in an outbox (`cf_pending_transfers`) and produced to `cohort_merge_state_transfer` keyed by the resolved survivor; a redrive loop re-produces stranded outbox entries, so a produce failure delays rather than loses the transfer. No `left` is emitted for `P_old`.
- **Phase 2, apply.** The receiving worker merges each transferred leaf under per-variant rules: a single-event bit is set true (it is never cleared, so the merge does not need to read either operand); daily buckets align both windows to the later of the two anchors and sum element-wise, so a stale disjoint window contributes nothing; compressed histories do the same when the catalog still knows the window length, and fall back to a plain union with a never-evict deadline when it does not. Merging can itself flip predicates, and those flips flow through the normal transition to Stage 2 to output path. Idempotence markers are keyed by the _original merge message's_ coordinates rather than the transfer's own offset, so forwards, redrives, and retries all short-circuit.
- **Chained merges.** If the target was itself already merged away, the apply handler forwards the transfer, hop-capped at 8. That cap bounds Kafka hops across partitions. A separate cap of 16 bounds the in-memory walk down a tombstone chain, which is cheap enough to allow more of; exhausting it applies at the last known hop rather than erroring, and that degraded target is not re-checked for partition ownership, so it can land off-partition.
- **Late events.** Events for `P_old` keep arriving for a while; the tombstone redirect folds them into the survivor (§8.4). Such an event carries a `redirected_from` origin, and dedup for it is keyed by that ancestor in `redirect_dedup` rather than folded into the main `applied_offsets` map, so replay protection survives the identity change without one person's offsets gating another's.

Tombstones and markers are GC'd on deadlines derived from upstream topic retention plus safety. That is an operator-maintained coupling, not a structural guarantee: the retention floors are pinned in config with a standing note that they must follow the topics' `retention.ms`, and `cf_pending_transfers` is never GC'd at all.

Three paths deliberately do **not** resolve tombstones: cascade messages, sweeps, and the backfill reconcile scan. The sweep case is consistent by construction, because the drain range-deletes the rows a sweep would visit and cancels their queue entries. The other two are known small gaps: a cascade or a reconcile emission for a person merged away mid-flight is attributed to the stale id.

Carrying membership register rows across a merge along with leaf state is separately gated (`COHORT_REGISTER_TRANSFER_ENABLED`, default off) because an older receiver would silently drop the field and delete the survivor's only register row. The payload covers every membership-registering class, not just single-leaf behavioral ones. Enable the sender only once the whole fleet can apply it.

## 12. Rebalancing and durability

A **rebalance** is Kafka reassigning partitions among the consumers in a group, which happens when a pod joins, leaves, or times out. Because a partition's state lives on the pod that owns it, a rebalance has to move state ownership too.

**Rebalancing** uses cooperative-sticky with static membership. On revoke, the synchronous callback only flips ownership flags; an async rebalance worker then unassigns the follower consumers _first_ (so merge, transfer, cascade, and seed fetch positions cannot advance past dropped messages), drops the partition's channel sender, awaits the worker's clean exit, forgets the partition's offset progress, resets its gauges, and **deletes the partition's on-disk state slice**. That deletion is the step that makes "never serves stale state" true. On assign, followers mirror the assignment at their stored offsets and the worker is spawned lazily on the first delivered batch. Correctness across a move is replay-based: the incoming pod re-folds the gap since the last commit, and per-key `applied_offsets` make the re-fold idempotent.

**Durability** is layered, and almost all of it is off at defaults:

- **The invariant is `committed <= durable`.** A Kafka offset may only be committed once the state it produced is durable locally. Since writes use an async WAL, the commit paths fsync the WAL first and _skip the commit_ if the fsync fails, so a crash loses at most the last uncommitted window, which Kafka then replays. The one exception is the restore path itself, which rewrites follower offsets from a checkpoint manifest without an fsync, because it runs before any folding.
- **Restore ladder at boot**, in strict order: reopen the live store if intact, then a recent checkpoint on the pod's persistent volume, then the latest S3 checkpoint, then cold start (wipe and rebuild from Kafka replay). Reopen-live wins even over a fresher checkpoint, because resume-from-committed is safe under `committed <= durable`. But reopen-live requires `DURABLE_RESTORE_ENABLED` and the middle two rungs require `CHECKPOINT_ENABLED`, both of which default off, so **a default deployment has only the cold-start rung** and a restart rebuilds from Kafka. An S3 restore that finds nothing usable also silently downgrades to cold start.
- Checkpoints are periodic whole-DB RocksDB checkpoints (hard-linked SSTs, so they must live on the same filesystem as the store) with incremental S3 upload and an offsets manifest captured after the fsync.
- `WIPE_STORE_ON_START` defaults to **true**, so re-acquiring a partition never serves stale state left by a previous owner. Durable restore suppresses it when a store directory is already present.
- **The single-pod caveat**: durable restore combined with cascade requires both `DURABLE_RESTORE_SINGLE_POD=true` and a pod identity; the flag alone still refuses to start. The restore path does not yet rebuild the merge column families, and cascade is the feature whose correctness most visibly depends on `cf_stage2` bits surviving a move, so the two together are refused unless the deployment is pinned to one pod.

## 13. The output, delivery semantics, and known limits

The product output is one message per membership flip, keyed by `person_id`:

```json
{
  "team_id": 42,
  "cohort_id": 1234,
  "person_id": "01928aaa-...",
  "last_updated": "2026-05-26 12:34:56.789123",
  "status": "entered"
}
```

`status` is `entered` or `left`. `last_updated` is in ClickHouse `DateTime64(6)` wire format, because a downstream consumer inserts these rows straight into a ClickHouse table, and it comes from a per-partition clock that floors on its previous value, so every later message from a worker is strictly newer even if the wall clock stalls or moves backward. Two optional fields, `origin` (`seed` or `reconcile`) and `run_id`, are added by the backfill paths only; they are omitted on live emissions, so the live wire format is unchanged.

The correct mental model for delivery is **at-least-once event delivery into an idempotent fold, with produce-gated commits on the output**, plus a small set of deliberate gaps.

- **Input is at-least-once.** Shuffler crash windows and processor replays redeliver events. The fold is idempotent against redelivery: `applied_offsets` (per source partition) skip already-folded offsets, and the record's stamp rejects stale updates, so state converges to the same value regardless of replays.
- **Output on the event path is effectively at-most-once per flip.** State commits _before_ the produce is confirmed, and a produce failure holds the offset so Kafka redelivers, but the redelivered event now hits already-updated state and replay dedup, so the missed flip is not re-derived. A crash in the wrong window can therefore drop a membership-change message while the state itself stays correct. This has to close before this pipeline replaces the batch one as the served source of truth; today the backfill reconcile snapshot ([backfill.md](./backfill.md) §5.8) is what repairs it.
- **Terminal produce failures at the shuffler abandon events**, counted, as a liveness-over-completeness choice.
- **Catalog staleness.** Cohort edits take up to one refresh cycle to take effect, and a persistently failing refresh keeps serving the last good catalog with only a log line.
- **No sub-day count windows.** An hour or minute window on `performed_event_multiple` is dropped at classification; a single `performed_event` with one is supported.
- **Cold start is replay-bounded.** State is built from the stream, so a new deployment only knows about events since it started consuming. "In the last 180 days" is under-counted until the pipeline has been folding that long, or has been backfilled. That is what [backfill.md](./backfill.md) is about.
- **Horizontal scaling is designed, not enabled.** 64 partitions and co-partitioned topics support multi-pod, but durable multi-pod operation is unvalidated and production runs single-pod.

## 14. Code map

**Shuffler** (`rust/cohort-event-shuffler/src/`): `consumer.rs` (two-phase gate plus main loop), `ledger.rs` (offset ledger), `filter_team_index.rs` (team gate), `event.rs` (output schema), `producer.rs` (murmur2 re-key), `config.rs`.

**Shared kernel** (`rust/cohort-core/src/`): everything the processor and the backfill seeder must agree on. `hogvm/` (executor and globals builders), `filters/` (loader, leaf classifier, tree, reverse index, cohort graph), `leaf_state/` (leaf state key derivation and variants), `bucket_tz.rs` (timezone day bucketing), `partitioner.rs` (murmur2), `eligibility.rs`, `seed/` (the backfill wire contracts).

**Processor** (`rust/cohort-stream-processor/src/`):

| Area                                | Files                                                                                                                                                        |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| consume, dispatch, backpressure     | `consumers/{events,merges,seeds}.rs`, `partitions/{router,intake,backpressure,pause,pacing,offset_tracker,rebalance,follower,watermarks,shuffle_message}.rs` |
| per-partition worker and event path | `workers/{worker,event_path}.rs`                                                                                                                             |
| catalog                             | `filters/manager.rs` (classification lives in `cohort-core`)                                                                                                 |
| Stage 1 state machines              | `stage1/{state,daily,compressed_history,person_record,predicate,transition}.rs`                                                                              |
| store                               | `store/{rocks,column_families,keyspace,keys,handle,staged,ttl_filter}.rs`, `store/durability/`                                                               |
| eviction                            | `sweep/{eviction_queue,scheduler,dispatch}.rs`, `workers/sweep_callback.rs`                                                                                  |
| Stage 2                             | `stage2/{evaluator,register,state}.rs`, `workers/{stage2_path,stage2_gc}.rs`                                                                                 |
| cascade                             | `cascade/{decision,message}.rs`, `workers/cascade_path.rs`                                                                                                   |
| merges                              | `merge/{rules,drain_handler,apply_handler,transfer,tombstone_redirect,bucket_align,compressed_concat,gc,redrive}.rs`                                         |
| backfill apply                      | `workers/{seed_path,person_seed_path,reconcile}.rs`, `sweep/reconcile.rs`                                                                                    |
| output                              | `producer/{mod,kafka,batcher,merge,cascade,marker,seed}.rs`                                                                                                  |

**Key configuration**:

| Env var                                                                         | Default                            | Purpose                                                                 |
| ------------------------------------------------------------------------------- | ---------------------------------- | ----------------------------------------------------------------------- |
| `REALTIME_COHORT_TEAM_ALLOWLIST`                                                | `2`                                | which teams the pipeline processes (`all`, `none`, or ids and ranges)   |
| `COHORT_PARTITION_COUNT`                                                        | `64`                               | asserted against the events topic at boot                               |
| `COHORT_EVENT_NAME_GATING_ENABLED`                                              | `true`                             | the event-name gate                                                     |
| `COHORT_CASCADE_ENABLED`                                                        | `false`                            | cohort-of-cohort re-evaluation                                          |
| `COHORT_CASCADE_DEPTH_CAP` / `COHORT_CASCADE_FANOUT_CAP`                        | 8 / 1000                           | cascade loop bounds                                                     |
| `COHORT_REGISTER_TRANSFER_ENABLED`                                              | `false`                            | carry membership register rows across a cross-partition merge           |
| `COHORT_BLOCK_CACHE_BYTES`                                                      | 128 MiB                            | shared RocksDB block cache                                              |
| `COHORT_TUNED_BLOCK_OPTIONS_ENABLED`                                            | `true`                             | cache and pin index and filter blocks                                   |
| `COHORT_PERSON_RECORD_TTL_DAYS`                                                 | `0` (off)                          | aging out dormant person records                                        |
| `COHORT_STORE_OFFLOAD_MODE`                                                     | `all`                              | which store calls leave the async runtime (`all`, `maintenance`, `off`) |
| `COHORT_STORE_EVENT_READ_PERMITS` / `COHORT_STORE_MAINTENANCE_PERMITS`          | 16 / 6                             | the two blocking-I/O lanes                                              |
| `DURABLE_RESTORE_ENABLED` / `DURABLE_RESTORE_SINGLE_POD` / `CHECKPOINT_ENABLED` | `false`                            | the durability ladder                                                   |
| `WIPE_STORE_ON_START`                                                           | `true`                             | wipe on boot unless durable restore finds a store                       |
| `COHORT_WIPE_ON_SCHEMA_MISMATCH`                                                | `false`                            | wipe rather than fail on a schema-version mismatch                      |
| `SWEEP_INTERVAL_MS` / `SWEEP_SAFETY_MARGIN_MS`                                  | 30000 / 300000                     | eviction tick and cutoff margin                                         |
| `COHORT_FIRST_EVICTION_SWEEP_DELAY_MS`                                          | 120000                             | delay before the first eviction pass after boot                         |
| `PARTITION_INTAKE_MAX_EVENTS`                                                   | 1024                               | per-partition admission budget                                          |
| `COHORT_MEMBERSHIP_CHANGED_TOPIC`                                               | `cohort_membership_changed_shadow` | output topic                                                            |

Backfill configuration is documented in [backfill.md](./backfill.md).
