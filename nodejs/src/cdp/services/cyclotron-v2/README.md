# Cyclotron (Node)

TypeScript job queue backed by PostgreSQL, using `pg` directly.

## Schema

Lives in a **separate database** (`cyclotron_node`) with its own migrations
in `rust/cyclotron-node-migrations/`.
Run them with `rust/bin/migrate-cyclotron-node`.

Single table `cyclotron_jobs` with a single `state` BYTEA column
for all job payload data (mirrors how the Kafka backend serializes everything into one blob).

## Components

### Manager (producer)

Creates jobs via `createJob()` / `bulkCreateJobs()`.
The bulk path uses `UNNEST` for efficient batch inserts.

### Worker (consumer)

Poll-based consumer using `FOR UPDATE SKIP LOCKED` to dequeue batches.
Each dequeued job exposes an ack interface:

- `ack()` — mark completed
- `fail()` — mark failed
- `retry({ delayMs?, state? })` — re-queue with optional delay and updated state
- `cancel()` — mark canceled
- `heartbeat()` — extend the lock to prevent the janitor from reclaiming the job

### Janitor (standalone service)

Runs on a timer interval as its own service (`PLUGIN_SERVER_MODE=cdp-cyclotron-v2-janitor`).
All operations use `FOR UPDATE SKIP LOCKED` so multiple janitor instances are safe.

Responsibilities:

- **Cleanup** — bounded `DELETE` of terminal jobs older than a grace period
- **Stalled job recovery** — reset jobs with stale heartbeats back to `available`
- **Poison pill recovery** — give up on jobs that have been reset too many times
  (`janitor_touch_count`), but never silently: each is _parked_ in place —
  the real row is kept, `scheduled` is pushed to `infinity` (so no worker dequeues
  it), the lock is cleared and `poison_retry_count` is stamped — and best-effort
  recorded as a `failed` `janitor_poison_pill` row on `hog_invocation_results` for
  visibility in the Invocations UI. The autodrain (below) releases parked pills back
  to their queue. Workers reset `janitor_touch_count = 0` on every deliberate
  release, so the budget counts CONSECUTIVE stalls — long-lived waits don't accrue
  touches for life.
- **Queue depth metrics** — Prometheus gauges per queue

### Poison-pill autodrain

Follows the co-located-singleton precedent of `appManagementSingleton` in the `cdp_api` mode.
The interval catches every tick and the service reports health best-effort, so a failing drain never crashes or restarts the janitor sharing its process.
The janitor _parks_ poison-pill give-ups (keeps the real row, `scheduled = infinity`, `poison_retry_count` stamped); recovering them was a manual operator rerun.
This service automates that recovery.

On each tick it runs a single Postgres UPDATE that releases parked poison pills back to their queue — `scheduled = NOW()`, `poison_retry_count = poison_retry_count + 1` — for rows where `poison_retry_count IS NOT NULL AND poison_retry_count < max_attempts AND status = 'available' AND scheduled = 'infinity'`, picked `FOR UPDATE SKIP LOCKED` up to a batch cap. A worker then re-runs the real job.

No ClickHouse in the loop — the retry decision reads and writes only strongly-consistent Postgres — so there is no ClickHouse-visibility lag that could re-select an already-run job. The release is one-shot by construction: once a row is released its `scheduled` is no longer `'infinity'`, so a later tick (or a concurrent janitor pod) can't re-release it, and it can't double-execute. `CYCLOTRON_POISON_PILL_AUTODRAIN_MAX_ATTEMPTS` bounds retries — after that the row stays parked (dead-letter); if the released job re-poisons, the janitor re-parks it (keeping the count). Throttled by `CYCLOTRON_POISON_PILL_AUTODRAIN_GROUP_BATCH` releases per tick and the tick interval.

Opt-in per environment via `CYCLOTRON_POISON_PILL_AUTODRAIN_ENABLED` (default off) — it is a new autonomous re-enqueue loop, so it stays off until validated.

## Integration

The `CyclotronJobQueuePostgresV2` wrapper in `job-queue/` bridges this SDK with the existing
`CyclotronJobInvocation` types used by CDP consumers.
It's enabled via `CDP_CYCLOTRON_NODE_ENABLED=true` and routed alongside the existing backends
(kafka, delay) in `CyclotronJobQueue`.

## No DLQ

Failed jobs are deleted by the janitor along with completed and canceled jobs.
There is no dead-letter queue — a DLQ would fill the database exponentially
since failed jobs often produce more failed jobs on retry, and it would be a
second recovery path operators have to learn alongside rerun.
Errors are captured via logs and metrics before the job reaches terminal status,
and poison-pill give-ups converge on the existing rerun system: they are written
as `failed` rows on `hog_invocation_results` (the table rerun already reads) and
deleted only once that row is durably enqueued, so a lost invocation is always
recoverable via the standard rerun tooling rather than a bespoke table.

## Future work

- **Activity table** —
  a separate table to store a high-level record of all run activities.
  Jobs are ephemeral (deleted after completion),
  so a durable activity log would give visibility into historical runs
  without keeping the jobs table unbounded.
- **Surfacing `action_id` for workflows** —
  the column exists and parked rows are indexed by it
  (`idx_cyclotron_jobs_action_reschedule`, used by the timing-edit reschedule sweep),
  but scheduled workflow actions still aren't queryable or displayable in product
  (e.g. "show me all pending actions for this workflow step").
- **Cancellation API** —
  API tooling to cancel scheduled jobs by query
  (e.g. by `function_id`, `parent_run_id`, or `action_id`).
  Especially useful for workflows where a user cancels a run
  and all its pending scheduled jobs need to be cleaned up.
