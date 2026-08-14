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

**Only consolidated schemas move.** `cdc_only` and `both` schemas produce two tables per run, which
one pipeline run cannot express, so they stay on legacy extraction. A source with a mix runs
hybrid — some schemas buffered, the rest unchanged — and keeps its backpressure guard for the
legacy ones.

Nothing is re-snapshotted. The slot, the Delta tables, and `initial_sync_complete` are all
preserved, so there is no WAL gap and no re-sync.

## Before flipping

1. `dwh-cdc-write-resolution` is on for the team. **The command refuses to flip without it.**
   Without the flag the loader records no load position, so no consumed file is ever proven safe to
   delete; the buffer then fills until the S3 TTL expires it, with the slot long advanced past those
   changes. That is unrecoverable loss, not a stall. Rollback does not require the flag.
2. Every CDC schema on the source is at `sync_frequency_interval = 5min`.
3. Buffer validation is clean over a busy window:

   ```bash
   python manage.py validate_cdc_buffer --source-id <uuid> --since-hours 40
   ```

4. Check what will move:

   ```bash
   python manage.py migrate_cdc_source_to_buffered --source-id <uuid> --dry-run
   ```

   Anything reported under "staying on legacy" keeps today's behavior.

## Flip

```bash
python manage.py migrate_cdc_source_to_buffered --source-id <uuid>
```

The command pauses the extraction schedule, waits for in-flight `sourcebatch` batches to reach a
terminal state, purges pre-flip buffer files, sets `job_inputs.cdc_ingest_mode = "buffered"`, then
unpauses the extraction schedule and each eligible schema's own schedule.

If a batch is still working after the drain timeout the command aborts with the source **left
paused**. That is deliberate — flipping on top of a stuck load lets that batch land against a table
the buffered lane has already started writing. Investigate the stuck load, then re-run.

Pre-flip buffer files are purged because the legacy lane already delivered those rows, and the load
position has no watermark for them yet.

### Verify

- Capture writes files under the schema's prefix and advances the slot (`cdc_last_log_position`
  moves).
- The next scheduled sync merges and advances `sync_type_config["cdc_load_position"]`.
- Consumed files disappear on the run **after** the one that read them — deletion follows the
  committed position, not the read.
- Row counts track the pre-flip day.
- `warehouse_load_cdc_delete_enrichment_violations_total` stays at zero.

## Rollback

```bash
python manage.py migrate_cdc_source_to_buffered --source-id <uuid> --rollback
```

Sets the mode back to `legacy`, re-pauses the per-schema schedules, and leaves the extraction
schedule running. Buffer files are **not** purged on rollback: the legacy lane has not delivered
them, and the position guard makes a stale replay a no-op. The 14-day S3 TTL clears the remainder.

Rows already merged stay merged — the same rows the legacy lane would have written.

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

Note for later: `both`-mode schemas create two `ExternalDataJob` rows per run, each carrying
`rows_synced`, so those customers are double-billed today. Buffered ingress halves it. That lands
with the companion lane, not this flip.
