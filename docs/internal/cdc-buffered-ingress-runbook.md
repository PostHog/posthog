# CDC buffered ingress — flip runbook

How to move a Postgres CDC source from legacy extraction onto the S3 change buffer, and how to move
it back.

## What changes

Capture stops transforming and dispatching change events. It decodes WAL, writes Parquet to
`s3://{DATAWAREHOUSE_BUCKET}/cdc_producer/{team_id}/{schema_id}/`, and advances the replication slot
as soon as those files are durable. The normal per-schema scheduled sync then consumes them like any
other source.

The point is that a stalled load can no longer hold the customer's WAL. It spends our S3 retention
instead.

**Every streaming table mode moves.** A run reads the buffer once and writes every table the mode
feeds, so `both` keeps its two tables at the same freshness as `consolidated` keeps its one.

**Each table gets its own job.** A `both` run creates a second `ExternalDataJob` for the `_cdc`
table, exactly as the legacy CDC extraction already does, and writes both from one read. That is
what keeps the load queue out of it: a job is where batch idempotency, S3 staging paths, claim
ordering and completion all hang, so two tables under one job would collide on every one of them,
while two jobs are two ordinary single-table runs the loader already knows how to finish.

The companion job carries no `workflow_run_id` and is not billable. The schema's own job owns the
v3 pipeline lock, and a second holder releasing it would free the lock while the run is still
writing; one read of a change stream is one sync however many tables it keeps, so only the
consolidated table's rows count towards usage. Its `schema_snapshot` records `cdc_write_mode` and
`companion_of`, which name the run it belongs to. If extraction fails, the activity marks its own
companion jobs failed — the stranded sweep finds runs by their queued batches, so a companion that
failed before staging anything has none to be found by.

Only a source that declares lanes runs the lane code. Every other source runs `PipelineV3` as it
was: the base class is the single-table path with extract-method seams, and `LanedPipelineV3` in
`pipeline_v3/lanes.py` overrides those seams. The activity picks the class from
`SourceResponse.lanes`. The load queue, the producer and the loader carry nothing about lanes at
all, so a single-table run finalizes exactly as before.

Schemas still snapshotting stay on legacy extraction until their first sync completes. A source
with a mix runs hybrid — some schemas buffered, the rest unchanged — and keeps its backpressure
guard for the legacy ones.

**Buffer files are deleted at the start of the next run**, before they are read, so the run that
proves a file consumed is never the run that deletes it. A file goes when it is strictly below the
floor — the lowest position any of the schema's tables holds — or when it sits exactly at the floor
and predates a listing by a run that went on to complete every table it writes. The floor alone is
not enough at its own boundary: capture flushes a transaction bigger than its budget across several
files that all carry that transaction's commit position, so a file at the floor may be the unread
tail of one. A completed listing is what proves otherwise. For a `both` run, both jobs have to have
completed, or a file could be deleted while the history table still owed it.

**A lane resumes from its own table.** A failed run can leave one table holding rows the other does
not, so each reads back the highest commit position it holds. The merge lane drops only what is
below that position: re-applying a row it holds is a no-op upsert, and dropping a row AT the
position would lose a later event for a key the table happens to hold at that same commit.

The append (`_cdc`) lane has no upsert, so a row written twice stays twice. It also reads back the
rows its table holds at that exact position, keyed by primary key and operation, and drops a batch
row only when that identity is one of them. A multiset, not a set: one transaction can change the
same key more than once and history keeps every version, so each match spends one. This is what
tells a row a previous run wrote from one nothing has seen — including a file capture wrote after
that run listed the buffer, which a bare count of rows at the position would have silently skipped.

Reading it back rather than recording it beside the table is what removes the crash window: a value
kept anywhere else can be lost between the write landing and the record of it, which either loses
changes or writes them twice. Nothing about a run is written to `sync_type_config`.

Delta keeps per-file min/max for its first 32 columns only, and the position column sits past that
on any real table. So every table a buffered lane writes declares `delta.dataSkippingStatsColumns`
naming the position column plus its primary keys, and for the history table its SCD2 `valid_to`
column, so the merges that predicate on them keep their pruning. Naming columns replaces the
default 32, which is why those are named too. Legacy CDC tables are untouched: that path strips the
position column before writing, and the property is never set on a table that lacks it.

A table whose files carry no statistic for the position column reports no position at all. That
re-applies rows its table may already hold, which both lanes absorb, and it is deliberately cheaper
than scanning a history table's whole column to avoid it. Two ordinary cases reach it: a companion
table's first write, before the property is set, and the tick after a repartition rewrites the
files. Buffer deletion pauses while any table is in that state, since the floor is unknown. A
persistent `cdc_position_stats_property_not_set` warning means a table never accepted the property,
and its buffer will grow to the S3 retention — investigate rather than wait.

**A run stands down while any delivery for the schema is still in the queue** — a legacy one, or a
previous attempt of this same job. Both would write alongside whatever this run reads, and on the
append lane that is a second copy of the same history. Two scheduled runs cannot overlap on their
own: the v3 pipeline lock is held from the start of the workflow until the loader completes the
job. The window is a retried activity, which runs under the lock its own workflow already holds,
and a lock takeover, which hands the lock to a new job while the old one's batches are still
queued. The run returns an empty response, which no-ops the tick and keeps the schedule alive. Nothing is
listed, so nothing is read, nothing is deleted, and the tick never counts as proof that a file was
consumed. The next scheduled run picks the buffer up once the queue has drained.

Nothing is re-snapshotted. The slot, the Delta tables, and `initial_sync_complete` are all
preserved, so there is no WAL gap and no re-sync.

## Before flipping

0. Pipeline version needs no preparation: the scheduled sync forces the v3 pipeline for every
   buffered schema, because only the v3 loader deletes the buffer files a completed job read. The
   team's `warehouse-pipelines-v3` rollout flag neither enables nor
   blocks the flip, and narrowing it later does not affect flipped sources. Do not flip while a
   deploy is rolling out, so every worker already runs the forcing.
1. `dwh-cdc-write-resolution` is on for the team. **The command refuses to flip without it.**
   The flag gates ordering resolution: dropping rows the table already applied, collapsing repeated
   keys within a batch, and checking that a DELETE is not about to erase columns the target still
   holds. Without it a buffered merge lane still lands every row, but out of order across a retry.
   Rollback does not require the flag. Neither deletion nor either lane's resume point depends on
   it: both come from the tables themselves.
2. No source table has a column named `_ph_cdc_seq`. **The command refuses to flip if one does** —
   the name is reserved for change ordering, and capture hard-errors on the collision rather than
   writing files whose ordering and retry cleanup derive from customer data. A source already on
   buffered carries the column for our own reasons, so the check only applies to a source still on
   legacy and a re-flip after a rollback is not blocked by it.
3. Every CDC schema on the source is at `sync_frequency_interval = 5min`. The command warns
   when an eligible schema is off cadence — consumption paces to the schema's own schedule.
4. Buffer validation is clean over a busy window:

   ```bash
   python manage.py validate_cdc_buffer --source-id <uuid> --since-hours 40
   ```

5. Check what will move:

   ```bash
   python manage.py migrate_cdc_source_to_buffered --source-id <uuid> --dry-run
   ```

   Anything reported under "staying on legacy" keeps today's behavior.

## Flip

```bash
python manage.py migrate_cdc_source_to_buffered --source-id <uuid>
```

The command pauses the extraction schedule, waits for the in-flight extraction run to finish,
pauses each eligible schema's schedule and waits for running sync jobs (a sync that started legacy
resolved its pipeline version then, and must not straddle the mode change), waits for in-flight
`sourcebatch` batches to reach a terminal state, purges pre-flip buffer files **and aborts if any
file survives the purge**, sets `job_inputs.cdc_ingest_mode = "buffered"`, then unpauses the
extraction schedule and each eligible schema's own schedule.

If a batch is still working after the drain timeout the command aborts with the source **left
paused**. That is deliberate — flipping on top of a stuck load lets that batch land against a table
the buffered lane has already started writing. Investigate the stuck load, then re-run.

Pre-flip buffer files are purged because the legacy lane already delivered those rows, and the load
position has no watermark for them yet.

The wait for the extraction run matters because pausing a Temporal schedule does not stop a workflow
already running. With the shadow lane on — the normal state before a flip, since validation needs
it — that run keeps writing buffer files, and one landing after the purge would be merged by the
consumer even though the legacy lane already delivered those rows.

The consumer also no-ops while any legacy delivery for the schema is in flight (deferred runs or
unfinished `sourcebatch` batches), so a legacy batch that lands late still lands before the first
buffered merge. The same gate holds the consumer off during a post-flip re-snapshot until the
deferred backlog lands.

### Verify

- Capture writes files under the schema's prefix and advances the slot (`cdc_last_log_position`
  moves).
- The next scheduled sync writes every table the mode feeds, from one read.
- The files that run read disappear at the start of a later run, once every table is past them.
- Row counts track the pre-flip day.
- `warehouse_load_cdc_delete_enrichment_violations_total` stays at zero.
- The schema's status in the Syncs UI now comes from the scheduled sync alone — capture heartbeats
  but never repaints a buffered schema COMPLETED, so a failing consumer run stays visible.

## Rollback

> [!IMPORTANT]
> Roll the source back to legacy **before** rolling the code back, and flip a `cdc_only` or `both`
> schema only once a deploy has finished rolling. A worker on the previous release does not treat
> those modes as buffered: it routes the schema into `CDCHandledExternally`, which pauses the
> per-schema schedule permanently. Capture keeps filling the buffer and advancing the slot while
> nothing consumes it, until the files age out of S3 retention.

```bash
python manage.py migrate_cdc_source_to_buffered --source-id <uuid> --rollback
```

The order matters, and the command enforces it:

1. Pause the extraction schedule, so no new capture run starts.
2. Wait for the in-flight extraction run to finish — pausing a schedule does not stop a running
   workflow, and a run still executing would keep writing files and advancing the slot behind the
   drain check.
3. **Wait for the consumer to drain the buffer.** The buffer's tail holds WAL the slot has already
   advanced past — it exists nowhere else, and flipping to legacy before it is applied loses it for
   good. The command refuses to proceed (extraction left paused, consumer left running) until every
   file is gone. The consumer deletes each file once the job that read it completes, so an empty
   prefix is its own proof that every change reached every table the mode feeds.
4. Pause the per-schema schedules and wait for running sync jobs, so no in-flight merge of old
   buffered rows can land after legacy delivery resumes and overwrite newer rows.
5. Set the mode to `legacy` and unpause the extraction schedule.

The buffer-drain check covers every schema the buffered lane serves, including ones disabled after
the flip — a disabled schema's unconsumed files still block, and draining them means re-enabling the
schema so its sync can catch up first. It skips the schemas that stayed on legacy: with the shadow
lane on, their prefixes hold validation copies no consumer reads, so scanning them would block the
rollback forever with capture paused.

Fully-applied buffer files are **not** purged: the completed job already deleted them, and the
14-day S3 TTL clears anything left. Rows already merged stay merged — the same rows the legacy lane would
have written.

## Buffer expiry — no partial recovery

Buffer files expire after 14 days (`expire-cdc-producer-buffer`). If a schema stops consuming —
paused, erroring, or wedged — its oldest unconsumed file ages toward that limit while the slot has
long since advanced past those changes.

**If files expire before they are consumed, the changes are gone.** There is no partial recovery.
The only fix is a full `reset_pipeline` re-snapshot for that schema.

Watch the age of the oldest unconsumed file per schema, not the file count. A schema with few files
that are all thirteen days old is in trouble; one with thousands of fresh files is fine.

## Known gap: zombie-attempt file collision

A Temporal activity attempt declared dead by heartbeat timeout can still be running and writing.
Buffer files are not idempotent overwrites — micro-batch boundaries shift between attempts — so a
zombie can overwrite a live attempt's file covering the same position range with fewer rows. Those
rows then exist nowhere, and the slot has advanced past them.

This is an accepted risk, not a fixed one. It needs a retry **and** a transaction spanning a flush
boundary **and** the boundary to shift between attempts.

There is no detector. `validate_cdc_buffer`'s continuity check compares adjacent filename ranges,
and in this failure the ranges stay contiguous — rows go missing inside a range.

Track `cdc_extract_retried_attempts_total` as the exposure proxy. A quiet counter bounds the risk;
a retry-heavy period is the signal to revisit. Candidate fixes are costed in the plan doc
(attempt-scoped prefix; polling `activity.is_cancelled()` at flush boundaries).

## Billing

Consume runs are ordinary jobs: `billable=True`, `rows_synced` = consumed rows.

**One read of the change stream bills once, whatever it feeds.** A run counts one table's rows
towards usage: the `_cdc` table for `cdc_only`, and the consolidated table for `consolidated` and
`both`. So `both` bills the same as `consolidated`, and keeping a history table alongside the merged
one costs nothing extra.

This changes what `both` used to cost. Legacy extraction writes the two tables from two
`ExternalDataJob` rows and counts each event twice; buffered writes them from one and counts once.
Sources on `both` will see their synced-row count roughly halve when they flip.
