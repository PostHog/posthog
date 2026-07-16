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
  (`janitor_touch_count`), but never silently: each is recorded as a `failed`,
  replayable invocation result on `hog_invocation_results` (discoverable in the
  Invocations UI, re-runnable by the rerun tooling) _before_ the cyclotron row is
  deleted. Workers reset `janitor_touch_count = 0` on every deliberate release, so
  the budget counts CONSECUTIVE stalls — long-lived waits don't accrue touches for
  life.
- **Queue depth metrics** — Prometheus gauges per queue

### Poison-pill autodrain (standalone service)

Runs on a timer interval as its own service
(`PLUGIN_SERVER_MODE=cdp-cyclotron-v2-poison-pill-autodrain`).
The janitor _records_ poison-pill give-ups as replayable `failed` rows; recovering them was a manual operator rerun.
This service automates that recovery.

On each tick it discovers distinct `(team_id, function_kind, function_id)` groups whose latest lifecycle row is a not-deleted `failed` `janitor_poison_pill` under the attempts cap (within a recent `scheduled_at` window), then enqueues one rerun wrapper per group through the existing rerun tooling (`RerunJobManager`).

It converges without a cursor or state table:
`CYCLOTRON_POISON_PILL_AUTODRAIN_MAX_ATTEMPTS` bounds how many times a genuinely-always-poison group is drained (both discovery and the rerun paginator exclude over-cap invocations), and a rerun writes a `running` row that self-dedups the invocation out of discovery until it either completes or re-poisons with `attempts+1`.
Throttled by `CYCLOTRON_POISON_PILL_AUTODRAIN_GROUP_BATCH` groups per tick, `CYCLOTRON_POISON_PILL_AUTODRAIN_MAX_COUNT_PER_GROUP` invocations per group, and the tick interval.

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
- **`action_id` column for workflows** —
  an additional indexed column so scheduled workflow actions
  can be queried and displayed more effectively
  (e.g. "show me all pending actions for this workflow step").
- **Cancellation API** —
  API tooling to cancel scheduled jobs by query
  (e.g. by `function_id`, `parent_run_id`, or `action_id`).
  Especially useful for workflows where a user cancels a run
  and all its pending scheduled jobs need to be cleaned up.
