# CDP batch hogflow resolver: cyclotron-based design

**Status:** Draft (open questions resolved)
**Author:** @meikelratz (agent-assisted)
**Date:** 2026-06-24

## TL;DR

Today, when a user (or the scheduler) triggers a batch run that emails 50k–1M people, we dispatch a single Kafka message and a single Node consumer pages through ClickHouse, accumulating every workflow invocation in memory, then bulk-inserts the lot into Postgres at the end. If anything fails mid-pagination, **the entire batch is dropped** and the Kafka offset advances anyway.

This works at small scale. It can't get to the 1M batch ceiling we're about to enable:

- One slow ClickHouse page tips a 3s timeout (or even 30s after the in-flight fix) — geometric tail compounding means batch success rate collapses as pages grow.
- 1M invocations held in worker memory = 2–10 GB resident.
- 1M-row single INSERT is a multi-GB Postgres transaction.

Proposal: **move the batch resolver to a cyclotron job that processes one page per execution, stores its cursor in job state, and re-queues itself**. This is the same state-reentry pattern that `delay` and `wait_until_time_window` actions already use today. Retry, partial progress, and backpressure all come for free.

## What "batch trigger" looks like end-to-end today

The chain runs through five services:

```text
┌─────────────────────────┐
│ User clicks             │
│ "Send to audience"      │
│ (or: scheduler service  │
│  hits internal endpoint)│
└────────────┬────────────┘
             │
             ▼
┌──────────────────────────────────────────────────┐
│ Django (web)                                     │
│  POST /api/projects/<id>/hog_flows/<id>/batch_jobs│
│  → HogFlowViewSet.batch_jobs()                   │
│  → Creates HogFlowBatchJob row                   │
│     (products/workflows/.../hog_flow_batch_job.py)│
└────────────┬─────────────────────────────────────┘
             │ post_save signal
             ▼
┌──────────────────────────────────────────────────┐
│ Django (web)                                     │
│  create_batch_hog_flow_job_invocation()          │
│  HTTP POST to Node /cdp/batch_hogflow_invocation │
└────────────┬─────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────┐
│ Node (cdp-api)                                   │
│  postHogFlowBatchInvocation()                    │
│  Produces 1 Kafka message to                     │
│  cdp_batch_hogflow_requests                      │
└────────────┬─────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────┐
│ Node (cdp-batch-hogflow consumer)                │
│  ┌─────────────────────────────────────────────┐ │
│  │ do {                                        │ │
│  │   GET /internal/.../user_blast_radius_persons│ │
│  │   accumulate invocations IN MEMORY ◄────────┼─┼─── PROBLEM (1)
│  │ } while (has_more && < maxAudienceSize)     │ │
│  │                                             │ │
│  │ if (anything threw) {                       │ │
│  │   drop all invocations ◄────────────────────┼─┼─── PROBLEM (2)
│  │   commit kafka offset anyway                │ │
│  │ }                                           │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  Bulk INSERT N invocations into cyclotron_jobs ◄─┼─── PROBLEM (3)
│  (queue='hogflow', one transaction)              │
└────────────┬─────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────┐
│ Node (cdp-cyclotron-worker-hogflow)              │
│  Dequeues N individual invocations               │
│  Walks each workflow graph (delay, email, etc.)  │
└──────────────────────────────────────────────────┘
```

The first three steps (UI/scheduler → HogFlowBatchJob → Django HTTP to Node) work fine. The breakage is concentrated in the boxed consumer.

### The three stacked problems

| #   | Problem                                                             | 50k impact                  | 1M impact                                           |
| --- | ------------------------------------------------------------------- | --------------------------- | --------------------------------------------------- |
| 1   | All invocations in worker memory before dispatch                    | ~250 MB                     | Worker OOM (2–10 GB)                                |
| 2   | One failed page drops the whole batch; Kafka offset advances anyway | Lost batch + silent failure | Lost batch + silent failure                         |
| 3   | Single bulk Postgres INSERT at the end                              | Slow but works              | Multi-GB transaction, autovacuum / replication pain |

The in-flight timeout/retry PR ([#65843](https://github.com/PostHog/posthog/pull/65843)) reduces the most likely _trigger_ of problem 2 but doesn't fix 1 or 3.

## Proposed design

Replace the Kafka message + in-memory loop with a **cyclotron job that resolves the audience one page at a time, persisting its cursor between pages**.

### Trigger flow (no change)

UI / scheduler → Django `HogFlowBatchJob` row → post_save signal → HTTP POST to Node. Unchanged.

`HogFlowBatchJob` stays in Django app Postgres as the **immutable trigger record** — it carries the audit info (who triggered, when, with what filters / variables). The resolver writes back to it exactly once at the end (terminal status).

### What changes on the Node side

The Node endpoint that today produces a Kafka message **directly enqueues a cyclotron job** on a new queue, `hogflow_batch_resolve`. No Kafka involvement.

```text
┌─────────────────────────────────────────────────┐
│ Node (cdp-api)                                  │
│  postHogFlowBatchInvocation()                   │
│  → cyclotronManager.createJob({                 │
│       queueName: 'hogflow_batch_resolve',       │
│       teamId, parentRunId,                      │
│       state: ResolverState (see below)          │
│     })                                          │
└────────────┬────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────┐
│ Node (NEW: cdp-cyclotron-worker-batch-resolve)  │
│  Dequeues one resolver job                      │
│  Processes ONE PAGE                             │
│  Re-queues itself with updated cursor           │
│  OR acks if done                                │
└─────────────────────────────────────────────────┘
```

The resolver queue is **plain FIFO** — no fair-dequeue. Reasoning: workflow execution is cheap (not externally throttled). The only place fairness matters is the email queue, which already has it via the SES throttle. Resolver self-requeues after each page, so under FIFO multiple concurrent batches naturally rotate page-by-page.

### Resolver job state shape

Stored in the cyclotron job's `state` BYTEA field:

```ts
interface BatchResolverState {
  batchJobId: string // == HogFlowBatchJob.id, == parentRunId on children
  teamId: number
  hogFlowId: string
  filters: HogFunctionFilters
  variables: Record<string, unknown>
  groupTypeIndex?: number
  maxAudienceSize: number
  cursor: string | null // null = first page
  totalEnqueued: number
  pagesProcessed: number
  startedAt: string // ISO timestamp
}
```

### Resolver worker lifecycle

```text
dequeue resolver job
  │
  ├─ if totalEnqueued >= maxAudienceSize:
  │     [truncation path — see below]
  │
  ├─ getBlastRadiusPersons(team, filters, cursor)   [one page, 500 persons]
  │     │
  │     ├─ transient failure → retry({delayMs: 500, state})   [cursor unchanged]
  │     └─ success → continue
  │
  ├─ build 500 CyclotronJobInvocation objects (workflow children)
  │
  ├─ ATOMIC (one Postgres TX in cyclotron DB):
  │     INSERT 500 children into cyclotron_jobs (queue='hogflow')
  │     UPDATE resolver job: state += page, status appropriately
  │
  └─ next:
       ├─ if has_more && totalEnqueued < maxAudienceSize:
       │     → retry({delayMs: 0, state})    [re-queue self for next page]
       │
       └─ else:
             → PUT Django: HogFlowBatchJob.status = COMPLETED
                 ├─ 200 → ack resolver job, done
                 └─ fail → retry({delayMs: 5s}) — try again later
```

### The atomic page commit (new cyclotron primitive)

To make per-page work crash-safe without an idempotency constraint, we add one primitive to the cyclotron worker API:

```ts
worker.bulkCreateAndCheckIn({
  newJobs: [...500 children],
  selfRetry: { delayMs: 0, state: newState }
})
```

Implementation: one Postgres transaction inside cyclotron that does `INSERT N children` + `UPDATE the current worker's row (state, status, scheduled, lock_id)` + `COMMIT`. If the worker dies before commit, neither write lands; the page replays cleanly on retry.

This is a real new primitive but a clean one — "produce work and check yourself back in" is a natural operation that other fan-out workflows will want too.

### Terminal status write to Django

The resolver's last act is a PUT to a new internal Django endpoint:

```text
PUT /api/projects/<id>/internal/hog_flows/batch_jobs/<batchJobId>/status
{ status: "COMPLETED" }   # or "FAILED"
```

**Idempotent by design** — if the row is already in a terminal status, the endpoint returns 200 without changing anything. This means the resolver can keep retrying until the write goes through, without worry about double-application.

**The resolver only acks itself after the Django write succeeds.** If Django is down, the resolver retries via standard cyclotron retry semantics. Eventually Django comes back, the write lands, the resolver acks. No read-time reconcile needed, no background sweep.

This is the _only_ cross-DB write in the entire design, and it's one write per batch (not per-page), in the edge state.

### Truncation (`maxAudienceSize` exceeded)

When `totalEnqueued >= maxAudienceSize` at the start of a page, the resolver exits early and surfaces visibly on two surfaces:

1. **Customer-facing workflow log** — `hogFunctionMonitoringService.queueLogs` emits an entry: `"Audience exceeded the max cap of ${maxAudienceSize}, ${totalEnqueued} persons enqueued; the remainder did not receive this workflow."` Visible in the workflow run UI.
2. **Prometheus metric** — `cdp_batch_hogflow_audience_truncated{hog_flow_id}` increments. Alertable.

Status to Django is plain `COMPLETED` — the run completed, the truncation is observable via the log + metric. We _don't_ persist the truncation count as queryable data on `HogFlowBatchJob`:

- The log covers the "did everyone get this?" customer question (visible in run UI).
- The metric covers the "are we hitting caps often?" ops question (alertable).
- A persistent field would force a Django migration on this PR and adds a permanent maintenance cost for a "nice to have" use case (a UI badge or analytics query) that nobody has asked for yet.

If a later customer-support flow needs queryable truncation counts, it's a small follow-up migration to add `truncated_at_count` back. YAGNI in the meantime.

## What this design gets us, problem by problem

| Today's problem                         | Fixed by                                                                                 |
| --------------------------------------- | ---------------------------------------------------------------------------------------- |
| All invocations in memory               | One page (500) at a time                                                                 |
| Single 1M-row INSERT                    | 2000 × 500-row INSERTs                                                                   |
| Failed page drops everything            | Cursor in state → atomic page commit → cyclotron retry resumes from same cursor          |
| Kafka offset advances on silent failure | No Kafka — job stays in queue until acked or failed-after-retries                        |
| No backpressure                         | Cyclotron workers pull at their own rate                                                 |
| Worker OOM mid-batch                    | Stall detection (`resetStalledJobs`) picks up the unfinished job after heartbeat timeout |
| No mid-batch visibility                 | `pagesProcessed` and `totalEnqueued` in job state, queryable in Postgres                 |

## Failure modes

| Failure                                               | Behavior                                                                                                                                                                     |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Transient ClickHouse timeout on a page                | Cyclotron retries job, cursor unchanged, resumes                                                                                                                             |
| Persistent ClickHouse failure (max retries exhausted) | Job marked failed; resolver PUTs `HogFlowBatchJob.status = FAILED`. Children already enqueued continue normally.                                                             |
| Worker dies mid-page (before atomic commit)           | Atomic TX rolls back, no partial state. Cyclotron's stall detection makes the job available again after heartbeat timeout, another worker resumes the same page from cursor. |
| Django down at terminal write                         | Resolver retries the PUT with cyclotron retry semantics. Job stays alive (parked) until Django acknowledges. PUT is idempotent so repeats are safe.                          |
| Audience exceeds `maxAudienceSize`                    | Early ack with customer log + Prometheus counter (see "Truncation" above). Status stays `COMPLETED`, no separate field.                                                      |

## Design decisions (resolved open questions)

These were the open questions in the first draft of this doc, now resolved with rationale.

1. **Idempotency of child enqueue → atomic transaction via new primitive.** Cross-job atomicity within cyclotron DB is small extra API surface (`bulkCreateAndCheckIn`) and avoids the maintenance cost of a permanent `UNIQUE (parent_run_id, person_id)` constraint that would affect all hogflow inserts forever.

2. **HogFlowBatchJob storage → stays in Django.** No cross-DB transactions needed because the only Django write happens once per batch (terminal status), not per-page. Idempotent PUT + cyclotron retry handles eventual consistency without read-time reconcile or background sweeps.

3. **Resolver queue fairness → plain FIFO, no fair-dequeue.** Workflow execution is fast (not externally throttled). The only real throttle is SES at the email queue, which already has fair-dequeue. Resolver self-requeues per page so under FIFO multiple concurrent batches naturally rotate.

4. **Cancellation → out of scope.** Batch cancellation isn't a product feature today; not in v1.

5. **`maxAudienceSize` enforcement → per-page state check + customer log + Prometheus counter, no DB field.** Status stays `COMPLETED`. We _do not_ persist the truncation count on `HogFlowBatchJob` — the log + metric cover the realistic customer and ops use cases, and dropping the field eliminates a Django migration from this PR (the "migrations + service in same PR" rule) plus a permanent maintenance cost. If a future customer-support flow needs queryable truncation counts, it's a small follow-up migration to add the field back. YAGNI.

## Migration plan

**Phase 1 — already shipped (#65843):** Bandage the live failure mode with the timeout/retry PR.

**Phase 2 — build behind a flag:**

- Add new cyclotron queue `hogflow_batch_resolve`.
- Add new worker `CdpCyclotronWorkerBatchResolve`.
- Add new cyclotron primitive `bulkCreateAndCheckIn`.
- Add new Django endpoint `PUT /api/projects/<id>/internal/hog_flows/batch_jobs/<id>/status` (idempotent).
- Reuse `HogFlowBatchPersonQueryService` unchanged.
- Gate dispatch path with `CDP_BATCH_RESOLVER_USE_CYCLOTRON` env flag in `cdp-api.ts`:
  - Flag off → Kafka path (today)
  - Flag on → cyclotron path (new)

**Phase 3 — canary:** Enable on low-volume teams. Monitor `pagesProcessed` advances, no stalled jobs, child invocation counts match.

**Phase 4 — default on:** Flip default. Drain remaining Kafka topic backlog (should be ~empty). Run ~2 weeks.

**Phase 5 — delete:** Remove `CdpBatchHogFlowRequestsConsumer`, the `cdp_batch_hogflow_requests` Kafka topic, the env flag.

## Scope estimate

~1 engineering week:

- **Day 1:** Resolver worker skeleton, queue wiring, state shape, env flag.
- **Day 2:** Per-page execution loop, child enqueue, cursor advance. Implement `bulkCreateAndCheckIn` primitive.
- **Day 3:** Terminal status PUT to Django (idempotent endpoint, no schema migration). Truncation handling (log + metric only).
- **Day 4:** Tests (unit on resolver, integration end-to-end with 5k synthetic audience).
- **Day 5:** Canary deploy on flag, observe, iterate.

Phases 3–5 play out over the following 2–3 weeks at lower intensity.

## Audience semantics: what happens if the cohort changes mid-resolve

The pagination query is evaluated against ClickHouse's **current** state on each page, not against a snapshot at trigger time. During the minutes the resolver runs, four things can happen:

| Event                                                        | Outcome                                                         |
| ------------------------------------------------------------ | --------------------------------------------------------------- |
| Person joins cohort before resolver reaches their UUID       | Picked up on a later page                                       |
| Person joins cohort after resolver already passed their UUID | Missed (UUID below cursor, never re-scanned)                    |
| Person leaves cohort after they were already enqueued        | Still gets the workflow (their child invocation already exists) |
| Person leaves cohort before resolver reaches their UUID      | Skipped on that page's filter eval                              |

These semantics are **identical to today's Kafka-based consumer** — cyclotron doesn't change anything here, just inherits the same model. Customers who need point-in-time semantics should use a **static cohort**, which is itself a snapshot.

Stronger guarantees (snapshot at trigger time by materializing the full UUID list upfront) are possible but out of scope for v1 — they trade one expensive ClickHouse query at trigger time for live semantics.

## Out of scope

- **The audience query optimization.** `SELECT DISTINCT persons.id` with property filters is doing a team-wide scan; that's a separate, larger ClickHouse conversation. The resolver makes that cost survivable but doesn't fix it.
- **Frontend UX for batch progress.** Once `pagesProcessed` is in resolver state, the UI could show a progress bar. Separate ticket.
- **Batch cancellation.** Not a product feature today; revisit if customer demand appears.

## References

- Live stop-the-bleed: PR [#65843](https://github.com/PostHog/posthog/pull/65843)
- Cyclotron v2 fair-dequeue (email queue): PRs [#63909](https://github.com/PostHog/posthog/pull/63909), [#65200](https://github.com/PostHog/posthog/pull/65200)
- Existing state-reentry patterns: `nodejs/src/cdp/services/hogflows/actions/delay.ts`, `wait_until_time_window.ts`
- Today's batch consumer: `nodejs/src/cdp/consumers/cdp-batch-hogflow.consumer.ts`
- Django batch trigger entry: `products/workflows/backend/api/hog_flow.py:1537` (`batch_jobs`), `:1697` (`internal_process_due_schedules`)
- Cyclotron job state encoding: `nodejs/src/cdp/services/cyclotron-v2/job-queue-postgres-v2.ts`
