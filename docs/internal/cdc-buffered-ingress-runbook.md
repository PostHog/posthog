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

**Every streaming table mode moves.** `consolidated` and `cdc_only` each feed one table, so a run
serves it. `both` feeds two, and a pipeline run writes one table — its batches share a run id, a
batch-index sequence, an S3 staging folder, and a final batch that completes the job. So a `both`
schema alternates: each table is served every other run, which halves its freshness and leaves
neither table behind. Buffer files are deleted only once every lane has passed them.

Schemas still snapshotting stay on legacy extraction until their first sync completes. A source
with a mix runs hybrid — some schemas buffered, the rest unchanged — and keeps its backpressure
guard for the legacy ones.

The trailing buffer file is re-read on every sync until its deletion proof matures. The merge lane
absorbs that as a no-op upsert. The append (`_cdc`) lane cannot — history has no upsert — so it
records how many rows of its current position it has written, and a re-read skips exactly that many
before yielding the rest. The count is deliberately not a file name: a retried capture attempt
re-emits the same changes under different names and different batch boundaries, so anything keyed
on a file would resume at a coordinate that no longer exists. The rows of one transaction decode in
the same order every time, whatever files they land in.

While that count is non-zero the lane proves only the position BEFORE its own, so every file
holding that transaction stays undeletable — the count is spent against those rows, and losing one
of the files would spend it against rows that never landed. Watch
`cdc_buffer_cursor_rows_skipped_total`: it fires only on a genuine mid-transaction resume, so a
standing rate means runs keep dying partway through one.

Nothing is re-snapshotted. The slot, the Delta tables, and `initial_sync_complete` are all
preserved, so there is no WAL gap and no re-sync.

## Before flipping

0. Pipeline version needs no preparation: the scheduled sync forces the v3 pipeline for every
   buffered schema, because only the v3 loader records the load position that proves buffer files
   consumed. The team's `warehouse-pipelines-v3` rollout flag neither enables nor
   blocks the flip, and narrowing it later does not affect flipped sources. Do not flip while a
   deploy is rolling out, so every worker already runs the forcing.
1. `dwh-cdc-write-resolution` is on for the team. **The command refuses to flip without it.**
   The flag gates ordering resolution: dropping rows the table already applied, collapsing repeated
   keys within a batch, and checking that a DELETE is not about to erase columns the target still
   holds. Without it a buffered merge lane still lands every row, but out of order across a retry.
   Rollback does not require the flag.
   Deletion no longer depends on it: the load position is recorded whatever the flag says, because
   withholding it leaves the buffer growing to the S3 TTL with the slot long advanced past those
   changes, which is unrecoverable loss rather than a stall.
2. No source table has a column named `_ph_cdc_seq`. **The command refuses to flip if one does** —
   the name is reserved for change ordering, and capture hard-errors on the collision rather than
   writing files whose ordering and retry cleanup derive from customer data. A schema that already
   consumed the buffer carries the column for our own reasons, and its recorded load position tells
   the check apart from a real collision, so a re-flip after a rollback is not blocked by it.
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
- The next scheduled sync merges and advances `sync_type_config["cdc_load_position"]`.
- Consumed files disappear on the run **after** the one that read them — deletion follows the
  committed position, not the read.
- Row counts track the pre-flip day.
- `warehouse_load_cdc_delete_enrichment_violations_total` stays at zero.
- The schema's status in the Syncs UI now comes from the scheduled sync alone — capture heartbeats
  but never repaints a buffered schema COMPLETED, so a failing consumer run stays visible.

## Rollback

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
   remaining file sits strictly below the schema's load position. A file ending exactly at the
   position does not count: one transaction shares a commit position across its events, so that file
   can still be the unread tail of a transaction split across files. The consumer settles it by
   deleting the file once a completed run proves it read it, which takes a tick or two.
4. Pause the per-schema schedules and wait for running sync jobs, so no in-flight merge of old
   buffered rows can land after legacy delivery resumes and overwrite newer rows.
5. Set the mode to `legacy` and unpause the extraction schedule.

The buffer-drain check covers every schema the buffered lane serves, including ones disabled after
the flip — a disabled schema's unconsumed files still block, and draining them means re-enabling the
schema so its sync can catch up first. It skips the schemas that stayed on legacy: with the shadow
lane on, their prefixes hold validation copies no consumer reads, so scanning them would block the
rollback forever with capture paused.

Fully-applied buffer files are **not** purged: the position guard makes a replay a no-op, and the
14-day S3 TTL clears them. Rows already merged stay merged — the same rows the legacy lane would
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

Consume runs are ordinary jobs: `billable=True`, `rows_synced` = consumed rows. A consolidated
source bills the same change events once per run, so the flip is billing-neutral by construction.
One bounded exception: the trailing file of a burst is re-read for a tick or two until a completed
run proves it consumed and it is deleted. On the merge lane those rows re-apply as no-op upserts in
that window, never perpetually, and they are counted in `rows_synced` for that run because the
count precedes resolution. The append lane skips them as it reads the file, so they never enter a
batch and are never counted.

`both`-mode schemas count each change event twice, once per table it feeds. That is unchanged by
the flip: legacy writes both tables every tick from two `ExternalDataJob` rows, and buffered writes
one table per tick from one job, so each table still receives — and counts — every event. Whether
feeding a second table should bill twice is a pricing question, open either way.
