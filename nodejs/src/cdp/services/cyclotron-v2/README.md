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
- **Poison pill detection** — dead-letter jobs that have been reset too many times (`janitor_touch_count`)
- **Queue depth metrics** — Prometheus gauges per queue (plus dead-letter depth)

## Integration

The `CyclotronJobQueuePostgresV2` wrapper in `job-queue/` bridges this SDK with the existing
`CyclotronJobInvocation` types used by CDP consumers.
It's enabled via `CDP_CYCLOTRON_NODE_ENABLED=true` and routed alongside the existing backends
(kafka, delay) in `CyclotronJobQueue`.

## Dead-letter queue (poison pills only)

Jobs that *fail* are deleted by the janitor along with completed and canceled jobs —
there is no failure DLQ, since failed jobs often produce more failed jobs on retry,
and errors are captured via logs and metrics before the job reaches terminal status.

Jobs the janitor gives up on (poison pills: stale heartbeat, reset more than
`maxTouchCount` times) are different: they are moved — full row, state, and a `reason` —
into `cyclotron_jobs_dead_letter` instead of being deleted, mirroring the V1 Rust
cyclotron's dead-letter queue. `CyclotronV2Manager.replayDeadLetterJobs()` re-inserts
them onto their original queue.

Dead-lettering is additionally gated on fleet health: if the share of stalled jobs
relative to recent completions spikes (a fleet-wide outage, not an isolated bad job),
the janitor pauses dead-lettering and only resets/retries until stalls return to
baseline. Workers reset `janitor_touch_count` on every deliberate release, so the
poison budget means "N consecutive stalls", not "N stalls over the job's lifetime".

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
