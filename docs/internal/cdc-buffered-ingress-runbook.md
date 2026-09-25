# CDC buffered ingress — runbook

How a Postgres, Supabase or Neon CDC source delivers its changes through the S3 change buffer, and how to operate it.

## How it works

Capture decodes WAL, writes Parquet to
`s3://{DATAWAREHOUSE_BUCKET}/cdc_producer/{team_id}/{schema_id}/`, and advances the replication slot
as soon as those files are durable. The normal per-schema scheduled sync then consumes them like any
other source.

The point is that a stalled load can no longer hold the customer's WAL. It spends our S3 retention
instead.

**Every table mode is served.** A run reads the buffer once and writes every table the mode
feeds, so `both` keeps its two tables at the same freshness as `consolidated` keeps its one.

**Each table gets its own job.** A `both` run creates a second `ExternalDataJob` for the `_cdc`
table and writes both from one read. That is
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

A table taking its snapshot has its changes captured to the buffer too, and the consumer reads them once the snapshot completes.
A marker on the schema, `cdc_snapshot_lane: "buffer"` in `sync_type_config`, records that the buffer carries the current snapshot.
Capture sets it, after emptying the table's buffer, the first time it sees the snapshotting table, before it reads the WAL, which drops files left from before a gap in capture such as a re-enable.
A reset of a table the buffer already serves (a resync, a table-mode switch, an admin re-snapshot, a TRUNCATE) sets it directly, because that buffer already holds an unbroken run of the table's changes.
The flip to streaming clears it.

While the marker holds, the hand-over deletes no buffer file.
The consumer replays all of them over the snapshot, including changes the snapshot already contains.
Replaying an unbroken run in order converges on the source's state, because the merge is an upsert by primary key.
A gap would break that, which is why the buffer is emptied when capture starts a snapshot there.
A snapshot that completes without the marker, because capture never ran for the table while it snapshotted, purges the whole buffer at the hand-over.

A TRUNCATE resets the table, empties its buffer, and drops that run's pending changes for it.
The reset also pauses the table's schedule and cancels its running sync, so a snapshot that began before a repeated reset cannot hand over without the changes the reset drops.
A cancel only asks the workflow to stop, and the loader still applies batches the sync queued, so while either is in progress the reset waits (`cdc_reset_waits_for_running_sync`).
The table then carries `cdc_reset_pending`, capture leaves it out, and each later run tries the reset again before it reads the WAL.
The new snapshot reads the table after the reset, so nothing skipped is lost.
The key stays until the schedule is unpaused, so a failed unpause is retried too.
A reset from slot-invalidation recovery marks the key `awaiting_slot` until the replacement slot exists, so no later run can unpause the table before capture has a point to resume from, and the table stays out of capture until then.
Recovery clears the flag once the slot is back, and so does any read that succeeds, so a failure right after the recreation cannot leave the table waiting for good.
Turning a table's sync off, or adding it back to capture, drops its marker, because capture skipped the table in between and its buffer has a gap.
Capture handles a TRUNCATE only after every change of its transaction has been read, so no pre-TRUNCATE change can land in the buffer after the purge.
A table whose data was deleted is still streaming but not seeded; its next sync runs a full refresh and the buffer replays over it.

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
naming the position column, its primary keys, and for the history table its SCD2 `valid_to`.

Naming any column replaces the default window rather than extending it, so the declaration repeats
the table's own first 32 columns ahead of those. Without that repetition the declaration would strip
the min/max off every column the customer queries, and this property is the only thing that sets
them.

A merge table whose files carry no statistic for the position column reports no position and
re-applies rows as upserts, which is a no-op. A history table cannot afford that, since a replay it
does not recognise is a second copy of every row, so it falls back to scanning the position column
once and logs `cdc_position_scanned`. The next write lands with the statistic and the scan stops.
One such log line after a repartition is expected; the same line on every tick means the property
is not being accepted, and `cdc_position_stats_property_not_set` alongside it says why. Alert on
the pair: that table is paying a full column read every five minutes.

A repartition carries the live table's properties onto the rebuilt one, so its files keep the
statistic and nothing pauses.

The history lane reads back every row at its position, with its content, to tell a replay from a
new change. One bulk transaction can put millions of rows at one position, and reading them all
back every tick until the next change lands would exhaust memory before that change could be
staged. The rows are read a batch at a time, and only the rows _at the position_ count — a
compacted file holds most of the table, but the read filters it. Past `MAX_POSITION_ROWS` rows or
`MAX_POSITION_BYTES` of Arrow memory the lane keeps only the key columns from then on, logs
`cdc_position_identity_degraded`, and matches on key and operation alone for that tick; a bulk
change touches each key once, so nothing is lost by it. One such line per bulk change is expected.
The same line on every tick means the table's newest transaction is huge and nothing has landed
since — look at the source.

A **merge** table whose files never gain the statistic replays safely but never advances the
floor: no file is deleted, and the buffer is re-merged and re-billed every tick. It logs
`cdc_position_unreadable` each tick. Alert on it; the writer is not honoring the property.

**A table's first buffered run** declares the statistics property, and a table wider than 32
columns reports no position on that run, since none of its files carries the statistic yet. Its
residual buffer is merged once more and billed once; the next write lands with the statistic and the
position reads normally from then on.

**A run stands down while any delivery for the schema is still in the queue**: a previous attempt
of this same job, or a batch the retired legacy lane queued before its source was converted. Either
would write alongside whatever this run reads, and on the append lane that is a second copy of the
same history. Two scheduled runs cannot overlap on their
own: the v3 pipeline lock is held from the start of the workflow until the loader completes the
job. The window is a retried activity, which runs under the lock its own workflow already holds,
and a lock takeover, which hands the lock to a new job while the old one's batches are still
queued. The run returns an empty response, which no-ops the tick and keeps the schedule alive. Nothing is
listed, so nothing is read, nothing is deleted, and the tick never counts as proof that a file was
consumed. The next scheduled run picks the buffer up once the queue has drained.

## Leftover legacy state

Capture used to deliver some tables' changes itself, on what is now the retired legacy lane.
That lane paused each such table's schedule while it streamed, held a snapshotting table's changes as deferred runs in `sync_type_config["cdc_deferred_runs"]`, marked its source `cdc_ingest_mode: legacy`, and created job rows of its own.
Capture converts that state before every read (`cdc/legacy_conversion.py`), so nothing needs doing by hand:

- **A source still marked legacy** has every CDC table's buffer emptied, since it holds only copies of changes the legacy lane already delivered.
  Each syncing table's schedule is rebuilt unpaused, because it is now the table's consumer.
  The source is then marked `cdc_ingest_mode: buffered`, last, so a failure repeats the whole conversion on the next run.
  Legacy batches still in the load queue land first, because the consumer stands down while any are in flight.
  Until then, a scheduled run of one of its tables, such as one a sync frequency change unpaused, no-ops the tick (`cdc_buffered_waiting_for_legacy_conversion`), because reading those copies would load them a second time.
- **A table with deferred runs** snapshots again in the buffer.
  Nothing merges deferred runs anymore, so its schedule is paused and its running sync cancelled.
  A cancel only asks the workflow to stop, and the loader can still apply batches the sync queued, so the reset waits for a later capture run while either is in progress (`cdc_legacy_snapshot_restart_waiting`).
  Capture leaves the table out until then, because the new snapshot reads the table after the reset.
  Then the table is reset, its buffer emptied, and its schedule rebuilt to start the new snapshot straight away.
  A failed or skipped rebuild keeps `cdc_schedule_resume_pending` on the table, and the next capture run retries it, so the snapshot starts once a deliberate hold below lifts.
- **A job row a legacy capture run left Running** is failed once it is 30 minutes old and has no batches in the queue.

A rebuilt schedule is skipped where the pause is deliberate: the schema's status is `Paused`, an admin-triggered run holds it, the schema is halted and waits for Repair CDC, or it has no sync frequency.
Every step logs (`cdc_legacy_source_converted`, `cdc_legacy_snapshot_restarted_in_buffer`, `cdc_stranded_capture_jobs_closed`); once none of them appears across the fleet, the module can go.

A source whose slot is gone does not capture at all, so it converts only after Repair CDC, which already resets every table and marks the source buffered.

`cdc_ingest_mode` must survive every API write. A PATCH that dropped it would make capture read the source as legacy and empty its unconsumed buffer.

## When a schedule stops firing

A per-schema Temporal schedule carries its own paused flag, written once when the schedule is
created or rewritten. Nothing reconciles that flag with `should_sync` afterwards, so a schedule
paused out of band stops a schema's syncs while every Postgres column still reports it as healthy:
`should_sync` true, `status` `Completed`, source enabled. No run starts, so there is no job row, no
`latest_error`, and no failure digest entry.

`sweep_stalled_schema_schedules` runs hourly and is the only thing that reports it. It publishes
`warehouse_stalled_schema_schedules`, labelled by kind:

- `no_runs`: nothing started. The schedule is the problem.
- `stuck_job`: a run started and never finished. Its workflow needs terminating first, which is
  what `unstick_external_data_jobs` does. Rescheduling alone changes nothing, because Temporal
  skips a tick while the previous run is still Running.

Repair is deliberately manual. Restarting a sync reaches into a customer's database, and the sweep
cannot tell a schedule paused by accident from one paused on purpose.

```bash
python manage.py repair_stalled_schema_schedules --source-type <type>            # dry run
python manage.py repair_stalled_schema_schedules --source-type <type> --live-run
```

The command clears a stale Running status, rewrites the schedule from `should_sync`, and recreates
a schedule that went missing. It triggers no run, so it bills nothing and each schema waits for its
own next tick. It stops at 100 schemas by default and refuses a wider match rather than acting on
it; raise `--max-schemas` deliberately.

A CDC table's schedule is the one that consumes its change buffer, so a stall there also lets the buffer age toward its 14-day expiry.

### What it will not touch, and where those go instead

A paused schedule is normal in more cases than it looks, so the command repairs only what it can
prove is the outage above. It re-checks every exclusion against a freshly loaded row at repair
time, because minutes can pass between the sweep finding a schema and an operator confirming the
prompt, and reports those as skips rather than repairs.

| Excluded                               | Why                                                                                     | Where it goes                    |
| -------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------- |
| `cdc_halted` schema                    | The marker exists to keep everything else off the schema until the halt clears.         | The source's `repair_cdc` action |
| `admin_unpause_schedule_after_run` set | The pause may belong to an in-flight admin-triggered run that clears the marker itself. | Wait for that run                |
| No `sync_frequency_interval`           | The schedule builder cannot turn a null interval into a cadence.                        | Set an interval first            |

## Buffer expiry — no partial recovery

Buffer files expire after 14 days (`expire-cdc-producer-buffer`). The API therefore rejects a CDC
sync frequency slower than `7day`. If a schema stops consuming —
paused, erroring, or wedged — its oldest unconsumed file ages toward that limit while the slot has
long since advanced past those changes.

**If files expire before they are consumed, the changes are gone.** There is no partial recovery.
The only fix is a full `reset_pipeline` re-snapshot for that schema.

Watch the age of the oldest unconsumed file per schema, not the file count. A schema with few files
that are all thirteen days old is in trouble; one with thousands of fresh files is fine.

A team over its billing limit is the usual cause.
The consumer is a scheduled sync, so it stops at the billing check, while capture keeps reading the WAL and writing the buffer, as webhook sources keep writing their events.
Once the limit lifts, the next sync loads the backlog, as long as none of it has expired.
Unlike the webhook prefix, `cdc_producer/` expires after 14 days.

## Retried capture attempts

Temporal retries a capture attempt that dies, and the retry re-reads the WAL from the slot's
confirmed position. Micro-batch boundaries are not stable across attempts, so the retry covers the
same positions with differently-shaped files. Before its first write per schema, it removes every
file that reaches the position it restarted from (`end_seq >= restart_seq`), because it is about to
re-emit all of those positions.

One file can straddle that position. A micro-flush is cut per event, so it can carry the head of a
transaction; the slot then advances only to the previous transaction's end, and the retry re-reads
the straddled transaction from its first row. That file holds settled positions the WAL no longer
has beside the head the retry re-emits. Deleting it loses the settled rows. Keeping it hands the
`_cdc` table a second copy of the head: the replay filter matches a batch row against what the
table already holds, and when both files are read in one run the table holds neither copy yet, so
both are appended. So the retry rewrites the file with its settled rows only, under the narrowed
range and the same index. The replacement is staged under a `.staging` suffix the consumer never
parses, the original is removed, and only then is the staged file promoted to its final name, so no
listing ever holds both. A crash anywhere in that sequence is finished by the next attempt's
cleanup: a staged file always holds settled rows, so it removes the original if it is still there
and promotes the staged file.

A cleanup failure fails the attempt. A superseded file that survives is a second copy of every
position it holds once the retry writes them again, so the run retries rather than write beside it.
`cdc_buffer_superseded_files_removed` in the capture logs carries `removed` and `trimmed` counts.

## Known gap: zombie-attempt file collision

A Temporal activity attempt declared dead by heartbeat timeout can still be running and writing.
Buffer files are not idempotent overwrites — micro-batch boundaries shift between attempts — so a
zombie can overwrite a live attempt's file covering the same position range with fewer rows. Those
rows then exist nowhere, and the slot has advanced past them.

This is an accepted risk, not a fixed one. It needs a retry **and** a transaction spanning a flush
boundary **and** the boundary to shift between attempts.

There is no detector. Adjacent filename ranges stay contiguous in this failure — rows go missing
inside a range.

Track `cdc_extract_retried_attempts_total` as the exposure proxy. A quiet counter bounds the risk;
a retry-heavy period is the signal to revisit. Candidate fixes are costed in the plan doc
(attempt-scoped prefix; polling `activity.is_cancelled()` at flush boundaries).

## Billing

Consume runs are ordinary jobs: `billable=True`, `rows_synced` = consumed rows.

**One read of the change stream bills once, whatever it feeds.** A run counts one table's rows
towards usage: the `_cdc` table for `cdc_only`, and the consolidated table for `consolidated` and
`both`. So `both` bills the same as `consolidated`, and keeping a history table alongside the merged
one costs nothing extra.

The retired legacy lane wrote the two tables from two `ExternalDataJob` rows and counted each event
twice, so a `both` source's synced-row count roughly halved when it moved to the buffer.

**The merge lane re-bills the rows at its position until the file holding them is deleted.** It
keeps every row at its position deliberately, since dropping one would lose a later event for the
same key at that same commit, and a kept row is a staged row. That is one transaction's rows, for
the tick or two until the completed-listing proof clears the file. The history lane matches those
rows by content and bills none of them.
