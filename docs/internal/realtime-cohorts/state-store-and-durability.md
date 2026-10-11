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

Durable restore, `DURABLE_RESTORE_ENABLED`, is off by default, and with it off the store is wiped at every start.
A deployment that relies on backfilled state must enable it.

With durable restore on, the processor picks where its store comes from at boot, in this order:

1. **Reopen the live store** on the persistent volume, if it is there.
   A store that carries a `restore.json` marker holds a checkpoint restore that has not finished, so that restore resumes instead (see [finishing a restore](#finishing-a-restore)).
2. **A local checkpoint**, if checkpoints are enabled and one was captured within `CHECKPOINT_LOCAL_MAX_STALENESS_SECS`.
3. **A remote checkpoint** from object storage, newest first, if checkpoints are enabled.
4. **An empty store**, the cold start, when checkpoints are disabled or nothing is restorable.

Before it decides, the boot deletes a leftover `<STORE_PATH>.restore` staging directory, which a restore killed midway leaves behind.
Checkpoints, `CHECKPOINT_ENABLED`, are disabled by default, so in practice the choice is between reopening the live store and starting empty.
A live store that fails to open does not fall back to a checkpoint: the pod fails to start.

A cold start does not rebuild history.
The consumers resume at their committed offsets, so the store only fills from new traffic, and every cohort's past membership has to come back through a backfill.
Its slices begin when their partitions are assigned, so the processor withholds every run whose boundary is earlier (see [slice coverage](#slice-coverage)).
A backfill cannot bring back everything.
`performed_event` leaves with an hour or minute window refill only from new live events, and a cohort made only of references refills through cascades from the backfills of the cohorts it references.

With durable restore on, the processor also:

- deletes the slices of partitions it no longer owns, with their coverage records, once its assignment settles,
- re-produces every transfer still waiting in the merge outbox,
- seeks every owned events partition back to the first event it polled during boot and did not dispatch,
- spawns a worker for every owned partition when boot ends, and each worker rebuilds its in-memory eviction queue from its behavioral rows,
- wipes the old slice of a partition that moves in after boot, with its coverage record, before its worker spawns, so the slice begins anew.

Nothing is dispatched to a worker, from the events consumer or a follower, until these boot steps end.
[Processor runtime](processor-runtime.md#startup) lists them in order.

When a partition is revoked, its worker drains and exits, and its slice is deleted with its coverage record.
State never moves between pods, which is why the processor runs as a single pod.
[Processor runtime](processor-runtime.md#rebalance-and-the-single-pod-constraint) explains that constraint.

### Choosing a checkpoint

The restore tries the freshest local checkpoint, then up to `CHECKPOINT_IMPORT_ATTEMPT_DEPTH` remote ones from the last `CHECKPOINT_IMPORT_WINDOW_HOURS`, newest first.
A checkpoint counts only once its `metadata.json` exists, because the sweeper and the upload both write it last.
A local attempt without one is passed over for the attempt before it, and a remote attempt without one is unusable and does not count toward the depth.
The restore judges each candidate from its `metadata.json` and `offsets.json` before the bulk download:

- its store schema must be this build's,
- its metadata and manifest formats must be ones this build reads,
- its manifest must belong to this pod's ordinal,
- the broker must still hold the events the checkpoint lacks on at least one partition (see [the replay window](#the-replay-window)).

A candidate that passes is materialized in `<STORE_PATH>.restore`, a sibling of the store on the same mount.
A local checkpoint is hard-linked there, SSTs only, with every other file copied.
A remote one is downloaded there, within `CHECKPOINT_IMPORT_TIMEOUT_SECS`.
The stage must open read-only with this build's column families and schema, and RocksDB's open checks that every SST its MANIFEST names is present at the recorded size.
The replay window is then checked again, because a download can outlast part of it.
The restore rewrites `uploaded.json` for the restored store, writes the `restore.json` marker into the stage, and renames the stage onto the store path.
A kill at any point leaves either the stage, which the next boot deletes, or a published store with its marker.

The first candidate that publishes wins, and no older one is downloaded.
When none publishes:

| What the candidates were    | Outcome                                               |
| --------------------------- | ----------------------------------------------------- |
| None, or only unusable ones | The store is created empty, behind the coverage fence |
| Any that failed             | The boot blocks and retries                           |

Unusable means an upload that never finished, a metadata or manifest format this build does not read, a schema mismatch while `COHORT_WIPE_ON_SCHEMA_MISMATCH` is on, or a checkpoint whose replay expired on every partition.
Older candidates are no better, so a retry cannot help.
A failed candidate is one that could restore after a fix: a download error, a stage that fails validation, a schema mismatch without the wipe flag.
A failed listing, a failed Kafka read and a local file error also block.

### A blocked restore

A blocked boot retries in process, with a backoff that starts at 30 seconds and doubles to 5 minutes.
The health server is already listening, so `/_health` answers and `/_ready` returns 503 with "events consumer boot recovery in progress".
`checkpoint_restore_blocked` reads 1 while it retries, and each round logs the error.
Every round measures the local staleness window and the remote listing window up to the first round's start, so a candidate that failed stays a candidate however long the boot blocks.
A candidate whose stage failed validation is not downloaded again in later rounds.
To give up on object storage, set `CHECKPOINT_ENABLED=false`.
The boot then creates the store, and every slice begins behind the coverage fence.

### The replay window

A restored slice is only correct if the broker can still replay every input past the checkpoint's position for it.
The restore checks each partition against the enabled inputs' watermarks:

- a partition the manifest does not list is reset,
- a partition where any enabled input's position lies outside the broker's `[low, high]` range is reset,
- every other partition resumes from its positions.

A reset deletes the slice and its coverage record, and fsyncs the write-ahead log, so the slice begins again behind the coverage fence.
Each reset counts in `checkpoint_restore_slices_reset_total{reason}` and logs its partition, its reason and the watermarks.
An input whose gate turned on after the capture has no position, so it resumes from its group's commit.
An input that is no longer enabled is ignored.

The check holds at boot, but the consumer still has to read past the oldest retained segment before retention deletes it.
A consumer whose position falls below the low watermark resets to `latest` for the events topic and `earliest` for the followers, without a trace.
So keep `CHECKPOINT_IMPORT_WINDOW_HOURS` below the events topic's retention by more than a restore's catch-up time.
A pod down longer than the window then lists no candidate and creates its store behind the coverage fence, which is the safe direction.
The window bounds only the listing: a restore already published resumes at any age, and the checks before and after the download, and at the settle, still catch a position that expired.

### Finishing a restore

A published restore stays pending until the events group commits the restored positions:

1. Before the store opens, the restore commits each follower group's positions on the partitions it keeps.
   A failure blocks the boot.
2. The store opens, and the resets apply.
3. The events consumer seeks each owned partition to the lower of its restored position and the first event it polled, commits that seek list, then deletes the marker.
   A failed watermark read, commit or delete keeps boot rewinding, and the next poll retries.
   Before the commit it checks every restored position on the partitions it owns again, on every input.
   If the broker expired one since the boot checked it, the consumer stops the process instead, and the next boot's check resets that slice.
4. Boot ends only then, so no worker folds, no follower dispatches and no checkpoint runs before the marker is gone.
   The followers are assigned at their restored positions while boot settles, but they dispatch nothing.

A crash before step 3 ends resumes the restore at the next boot.
The replay window is checked again, because the broker may have expired more of it, and the follower commits repeat.
An unreadable marker means the positions are unknown, so the boot deletes the store and restores again.
It renames the store to the staging path first, so a deletion cut short never leaves a store that reopens without its marker.

## Checkpoints

With `CHECKPOINT_ENABLED`, the processor takes a whole-store RocksDB checkpoint into `CHECKPOINT_LOCAL_DIR` every `CHECKPOINT_INTERVAL_MS`, and uploads one in every few to object storage, at `CHECKPOINT_S3_UPLOAD_INTERVAL_MS`.
The loop starts when boot ends.
Checkpoints require durable restore, a bucket, and an absolute checkpoint directory on the store's filesystem but outside the store and its `<STORE_PATH>.restore` staging directory, and the pod fails at start without them.

- **One lineage per pod.**
  A pod's checkpoints live under `cohort_stream_state/<ordinal>`, locally and in object storage, where the ordinal is the number that ends the StatefulSet pod name in `POD_NAME`.
  Ordinal 0 keeps the single pod's original layout.
  Two pods never read or write each other's checkpoints.
- **Positions from the broker.**
  Each checkpoint carries `offsets.json`: for every owned slice, the committed offset of every enabled input's consumer group, or the low watermark where the group has none, so idle partitions are recorded too.
  The positions are read after a write-ahead-log flush and before the checkpoint.
  Every commit follows a flush of its own, so the checkpoint holds at least the state the positions cover.
- **Incremental uploads.**
  An upload sends only the files its predecessor in the chain lacks.
  A restarted process builds on the last upload, recorded locally in `uploaded.json`, only while the store's RocksDB DB id matches it, because a created store reuses SST file names.
  A restored store also reuses the SST numbers written after its checkpoint, so a restore from object storage makes the restored checkpoint the baseline, and a local restore removes the baseline, which makes the next upload full.
  Once a chain is older than `CHECKPOINT_FULL_UPLOAD_INTERVAL_SECS`, the next upload is full, which bounds the age of the oldest object a restore needs.
- **Paced uploads.**
  One upload reads at most `CHECKPOINT_UPLOAD_MAX_BYTES_PER_SEC` from the store's disk across all its files, so a full upload does not starve the live path.
- **A final checkpoint.**
  A graceful stop cancels a periodic upload in flight, takes one more checkpoint once every consumer has made its final commit, and uploads it.
  The upload is cancelled after `CHECKPOINT_FINAL_UPLOAD_TIMEOUT_SECS`, but an S3 request in flight runs to its end, so the checkpoint component's shutdown window is the hard limit.
  An upload stopped before its `metadata.json` is not restorable, so the last finished upload stays the newest restorable one.
- **No expiry.**
  Objects are not expired.
  An expiry, when one is set, must exceed the full-upload interval plus the import window.

The uploader is built on the first upload, so an outage of object storage never stops a pod that has its store.
A failed build counts `checkpoint_uploads_total{result="unavailable"}`, and the next upload tries again.

These metrics follow checkpoints:

- `checkpoint_last_upload_timestamp_seconds` is the last successful upload, and starts at process start, so a staleness alert fires only once its threshold passes,
- `checkpoint_last_capture_timestamp_seconds` and `checkpoint_last_full_upload_timestamp_seconds` are the last captured manifest and the start of the newest upload's chain,
- `checkpoint_uploads_total{result, trigger}` and `checkpoint_uploaded_bytes_total{kind}` count uploads and the bytes they sent,
- `checkpoint_capture_failures_total{reason}` counts ticks skipped before the checkpoint,
- `checkpoint_restore_total{source}` counts where each boot's store came from: `reopened`, `pending`, `local`, `s3` or `created`,
- `checkpoint_restore_candidates_total{verdict}` counts the candidates a restore tried,
- `checkpoint_restore_blocked` reads 1 while a restore blocks the boot.

## Slice coverage

A slice is one partition's state in one store.
A slice that lost its history looks like any other empty slice, so each slice carries a coverage record.
The record says either that the slice is complete, or that it holds every event its partition delivered after an instant, and maybe some before.
It lives in `cf_person_records` under a 3-byte key, `[partition][0xFE]`, which no person-record read reaches.

| What happens                                                                                          | Coverage                                                                                                                          |
| ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| The store is created: none on disk, a wipe at start, a wipe on schema mismatch, or nothing to restore | The open stamps `cf_meta[slice_coverage]`, with no records. Each slice begins when its partition is assigned                      |
| A store with the stamp reopens                                                                        | Each slice resumes its own record                                                                                                 |
| A store without the stamp reopens                                                                     | It predates coverage records. The open writes `complete` for every partition and the stamp in one batch, so it adopts once        |
| A revoke, the boot deletion of an unowned partition, or a move-in wipe                                | `delete_partition` deletes the record with the slice, and the next worker begins the slice anew from its assignment               |
| A checkpoint restore                                                                                  | The record and the stamp travel inside the checkpoint. A slice the restore cannot replay is reset with its record and begins anew |

A reconcile certifies its partition only when the slice holds the run's history: the slice is complete, or it began at or before the run's boundary.
Otherwise the partition withholds the run, as [the reconcile guard](seed-apply-and-reconcile.md#the-walk) describes, and its `covered_since` is the boundary a disaster-recovery run must pin.

The record is written once and only deleted with its slice, which makes a rollback safe.
An older image never reads the record or the stamp, and its own partition deletes remove records with their slices.
A rolled-back image that recreates the store leaves a store without the stamp, and the next open adopts it as complete.
That is the trust every store had before coverage records existed.

Coverage does not detect a stale slice, one whose partition another writer advanced while this store held older state.
With one pod, only a rollback of the store produces one.

Three metrics follow coverage:

- `cohort_slices_adopted_total` rises by the partition count at an adopting open,
- `cohort_slices_begun_total` counts slices that began without earlier history,
- `cohort_slice_covered_since_seconds{partition}` is when each owned slice began, and 0 for a complete one.

## Keeping the store bounded

- **Behavioral rows** leave through the sweep, which deletes rows that aged out and emits `left` on the way.
  They are never expired by RocksDB itself, because an expiry that RocksDB performs silently would skip the `left`.
- **Person records** can be expired by a compaction filter on a last-seen time, when `COHORT_PERSON_RECORD_TTL_DAYS` sets a time-to-live. It defaults to 0, which turns expiry off.
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

- an **event** pool, for live-path reads and for Stage 2 recomposition on the live, sweep, merge and cascade paths,
- a smaller **maintenance** pool, for the sweep's state reads, merge drains and applies, garbage collection, reconcile pages and backfill seed runs.

Plain writes and the write-ahead-log flush take no permit, so the commit cadence never waits behind reads.
A lint rule denies direct calls to most store I/O methods, and the synchronous sections that need them opt out explicitly.

## Things that surprise people

- Reopening the live store checks only that RocksDB's `CURRENT` file exists.
  A damaged store that has one is chosen, fails to open, and the pod crash-loops.
  It never falls back to a checkpoint.
- With checkpoints disabled, a store directory without a `CURRENT` file is neither reopened nor wiped, and the open fails on the missing schema stamp.
  With checkpoints enabled, the boot deletes it and restores.
- A store directory that holds `restore.json` is a checkpoint restore in progress, not a live store.
  An image from before that marker ignores it and reopens the store at the broker's old offsets, so do not roll back while a restore is pending.
- Static group membership keeps a restart from causing a revoke.
  A second group member, or a pod that loses its session or stops polling, still causes one.
  Each revoke deletes the whole slice, including merge transfers not yet sent, whose merge offsets may already be committed.
- Person records grow with every person seen on a team with person-property conditions, including those that match nothing, unless a time-to-live is configured.
- The person record time-to-live is judged against event time, so importing old events can write records that are already eligible for expiry.
