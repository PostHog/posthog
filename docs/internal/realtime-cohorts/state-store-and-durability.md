# State store and durability

The processor keeps all membership state in an embedded RocksDB database on the pod's disk.
This page explains the store's layout, why it is shaped around the person, how writes stay atomic, what "durable" means for the processor, and how it restarts.

It uses terms from [live evaluation](live-evaluation.md) (leaf state keys, the person record, Stage 2, replay marks), [merges and cascades](merges-and-cascades.md) (drains, tombstones, the transfer outbox) and [time and eviction](time-and-eviction.md) (the sweep).

## Kafka is the log, RocksDB is the view

The processor treats its input topics as the source of truth and the store as a local materialization of them.
Any state could in principle be rebuilt by replaying input, but the events topic keeps about a day and the merge topics about a week, while windows reach back months.
So the store is precious in practice.
Losing it means rebuilding from backfills, not from Kafka.

There is one RocksDB database per pod, holding every partition the pod owns.
Every key except the schema stamp starts with the partition number, so one partition's state is one contiguous key range.
Wiping a partition is one range delete per partitioned column family.

## Column families

A column family is a separate keyspace inside the database, with its own settings.

| Column family             | One row per                          | Holds                                                                                                                                                                                                                                                                                        |
| ------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cf_behavioral`           | person and behavioral leaf state key | Behavioral leaf state, its eviction deadline, and replay marks: the firehose offsets already applied                                                                                                                                                                                         |
| `cf_person_records`       | person                               | The person record: matched person conditions, fingerprints, stamp, replay marks                                                                                                                                                                                                              |
| `cf_stage2`               | cohort and person                    | The membership bit the processor registered for the pair. On the live, sweep, merge, cascade and reconcile paths it is the recomputed truth. On the seed path it is what downstream was last told. Also reconcile dirty markers, and an inventory of membership rows received through merges |
| `cf_merge_drains_applied` | merge message                        | Marker: this merge was drained                                                                                                                                                                                                                                                               |
| `cf_merge_applied`        | merge message and target             | Marker: this transfer was applied                                                                                                                                                                                                                                                            |
| `cf_pending_transfers`    | merged-away person                   | Outbox of state waiting to be transferred to another partition                                                                                                                                                                                                                               |
| `cf_merge_tombstones`     | merged-away person                   | Forwarding address to the survivor                                                                                                                                                                                                                                                           |
| `cf_meta`                 | store                                | The schema version                                                                                                                                                                                                                                                                           |

## Keys are clustered by person

Behavioral rows and person records are keyed by a 26-byte **person prefix**:

```text
person prefix = [partition u16][team u64][person uuid 16 bytes]

cf_behavioral key     = person prefix + leaf state key (16 bytes)
cf_person_records key = person prefix
cf_stage2 key         = [partition][team][cohort u64][person]
```

Integers are big-endian, so byte order is numeric order.
All of one person's behavioral rows sort next to each other, and the person record uses the bare prefix as its key in its own column family.
The tombstone and outbox column families are keyed by the same prefix.

This layout is the most important performance decision in the processor.
An event touches only its person's rows, so its behavioral reads and its person-record read each hit one small key range, however large the store grows, plus a tombstone probe that a bloom filter usually answers.
Collapsing all of a person's person-property state into one record, with fingerprints that let most events skip evaluation, is what keeps the number of keys an event reads small.
Behavioral state is still one row per person and leaf the person matched.

The same clustering makes merges cheap.
Draining a person is one prefix scan and one range delete.

`cf_stage2` is the exception.
It is keyed cohort first, so reconcile can walk every row of one cohort as a range scan.
The cost is that a merge drain cannot list one person's Stage 2 rows by prefix.
It deletes them using the catalog's list of cohorts, plus a person-first inventory of rows it received through earlier merges.

## Writes are atomic per unit of work

A worker collects the changes of one unit of work into one batch and commits it as one RocksDB write batch.
Examples of a unit: one event's Stage 1 fold, one merge drain, one merge apply, one sweep batch's single-leaf leg, one cascade message, one reconcile page, one group of seed messages' Stage 1 writes.
A crash can never leave half of one: a merged-away person deleted without its tombstone, or a leaf updated without its single-leaf Stage 2 row.
Flushes are atomic across column families too.

Composed Stage 2 rows are always their own, later batch.
A crash between a Stage 1 batch and its Stage 2 batch drops that composed flip until the person's leaves flip again.
Reconcile also repairs it if the person already had a Stage 2 row for the cohort.
If the lost write would have been the person's first row, reconcile never sees the person, and only a seed or a later flip that touches them repairs it.

While a partition's worker runs, it is the only writer of its key range.
Merges, cascades, sweeps, garbage collection, backfill and reconcile all run on that worker, so reads always see the worker's own previous writes.
Partition wipes and the boot redrive of the transfer outbox run from outside the worker.
A revoke wipes a slice after its worker exits, and a partition that moves in after boot is wiped just before its worker spawns.
The boot redrive is meant to run before workers exist, but nothing enforces that, so a worker can already be running while it clears outbox rows.
[Processor runtime](processor-runtime.md#startup) describes the gap.
The processor needs no locks and no RocksDB snapshots.

## The durability invariant

Writes do not wait for the disk.
Each write batch reaches the write-ahead log in the operating system's page cache and returns.
Durability comes from the offset commit instead:

1. every few seconds, each consumer captures the offsets it is allowed to commit,
2. it forces the write-ahead log to disk,
3. only if that succeeds, it commits the captured offsets to Kafka.

So **a committed offset never runs ahead of state on disk**.
After a crash, Kafka redelivers everything after the last commit, and each path's idempotence absorbs the replay: replay marks for events, markers for merges, max-merge for backfill tiles.
The invariant holds for every input topic, whether or not durable restore is enabled.
It protects state, not output.
Output is acknowledged before the flush, so a host crash that loses unflushed writes can make the replay emit changes a second time.

It covers writes that succeeded.
A failed Stage 1 read or write on the live path skips the event without holding its offset, so that event's effect is lost from the leaf state.
Reconcile recomputes from that same state, so it cannot bring the event back.
Only a later backfill whose seeds cover the event restores it.

## Schema version

The store records a schema version in `cf_meta`.
Opening a store whose stamp is missing or different fails, unless `COHORT_WIPE_ON_SCHEMA_MISMATCH` allows a wipe.
A store with an unknown column family fails to open even with that flag.
There are no in-place migrations.
An incompatible key or value change bumps the version, and the store is rebuilt from nothing, which means re-running backfills.

## Restarting

Durable restore is off by default, and with it off the store is wiped at every start.
A deployment that relies on backfilled state must enable it.

With durable restore on, the processor picks where its store comes from at boot, in this order:

1. **Reopen the live store** on the persistent volume, if it is there.
2. **A local checkpoint**, if checkpoints are enabled and a recent one exists.
3. **A remote checkpoint** downloaded from object storage, if checkpoints are enabled.
4. **An empty store**, the cold start.

Checkpoints are disabled by default, so in practice the choice is between reopening the live store and starting empty.
A checkpoint restore that fails to clear the store, copy or download the checkpoint, or read its offsets falls back to a cold start.
The restore never opens the RocksDB files, so a checkpoint whose files cannot open passes it, and the store open that follows fails the pod instead.
A live store that fails to open does not fall back either: the pod fails to start.

A cold start does not rebuild history.
The consumers resume at their committed offsets, so the store only fills from new traffic, and every cohort's past membership has to come back through a backfill.
A backfill cannot bring back everything.
`performed_event` leaves with an hour or minute window refill only from new live events, and a cohort made only of references refills through cascades from the backfills of the cohorts it references.

With durable restore on, the processor also:

- deletes the slices of partitions it no longer owns, once its assignment settles,
- re-produces every transfer still waiting in the merge outbox,
- rebuilds each partition's in-memory eviction queue from its behavioral rows when that partition's worker spawns,
- wipes the old slice of a partition that moves in after boot, before its worker spawns.

After a checkpoint restore it also rewinds the consumers to the offsets recorded in the checkpoint.
The events consumer retries its seek until it succeeds.
It seeks only once its assignment settles, so a poll that arrives earlier is still dispatched, the same startup gap as the boot redrive.
The merge, transfer, cascade and seed followers get one attempt each.
A failed attempt only logs a warning, and a checkpoint with no offsets for the topic skips the rewind silently.
Either way the follower resumes at its broker-stored offsets.
Those can be ahead of the restored state, and the inputs in between are never applied.

When a partition is revoked, its worker drains and exits, and its slice is deleted.
State never moves between pods, which is why the processor runs as a single pod.
[Processor runtime](processor-runtime.md#rebalance-and-the-single-pod-constraint) explains that constraint.

## Keeping the store bounded

- **Behavioral rows** leave through the sweep, which deletes rows that aged out and emits `left` on the way.
  They are never expired by RocksDB itself, because an expiry that RocksDB performs silently would skip the `left`.
- **Person records** can be expired by a compaction filter on a last-seen time, when a time-to-live is configured.
  An expired record loses its matched set and its replay marks.
  On the person's next event, current matches re-emit `entered` for single-leaf cohorts, and a condition that stopped matching while the person was dormant cannot emit `left`.
  Keep the time-to-live well beyond topic retention.
- **Stage 2 rows** of cohorts that left the catalog are removed by the hourly Stage 2 garbage collection.
  The exception is a row received through a merge while register transfer is enabled, which the collection keeps until its protection ends.
  [Merges and cascades](merges-and-cascades.md#stage-2-garbage-collection) explains when that happens.
  Rows of live cohorts are never deleted, because a person who leaves keeps an explicit `false` row.
  So `cf_stage2` grows with every person who was ever registered in a live cohort.
- **Merge markers and tombstones** are removed after their retention period.
- **Orphaned behavioral rows**, left behind when a leaf's definition changes, a cohort is deleted, or a team leaves the catalog, are not collected.
  They are removed only by a merge drain or a partition wipe.

## Tuning that matters

- **One block cache** shared by all column families also holds index and filter blocks, so memory use is predictable.
- **Bloom filters** on every column family make misses cheap.
  That matters because every event probes the tombstone column family, and nearly every probe misses.
- **A prefix extractor** on the 26-byte person prefix makes one person's behavioral rows a single prefix scan.
- **Compaction on deletion** compacts files dense with deletes, which the sweep and merges produce in waves.
- **Range deletes** remove a person or a partition in one operation.

## Store access from async code

Workers are async tasks, and RocksDB calls block.
By default every store call runs on a blocking thread pool, and reads and whole maintenance sections take permits from two pools:

- an **event** pool, for live-path reads and for Stage 2 recomposition on every path,
- a smaller **maintenance** pool, for the sweep's state reads, merge drains and applies, garbage collection, reconcile pages and backfill seed runs.

Plain writes and the write-ahead-log flush take no permit, so the commit cadence never waits behind reads.
A lint rule denies direct calls to most store I/O methods, and the synchronous sections that need them opt out explicitly.

## Things that surprise people

- Reopening the live store checks only that RocksDB's `CURRENT` file exists.
  A damaged store that has one is chosen, fails to open, and the pod crash-loops.
  It never falls back to a checkpoint.
- A store directory without a `CURRENT` file is neither reopened nor wiped, and the open fails on the missing schema stamp.
- Static group membership keeps a restart from causing a revoke.
  A second group member, or a pod that loses its session or stops polling, still causes one.
  Each revoke deletes the whole slice, including merge transfers not yet sent, whose merge offsets may already be committed.
- Person records grow with every person seen on a team with person-property conditions, including those that match nothing, unless a time-to-live is configured.
- The person record time-to-live is judged against event time, so importing old events can write records that are already eligible for expiry.
