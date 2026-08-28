# Ingestion batch time budgets and partial completion

Status: proposal.
Scope: the Node.js ingestion pipelines framework (`nodejs/src/ingestion/framework/`), the WorkerIngest gRPC transport, and the Rust ingestion consumer's handling of partial acks.
The HTTP `/ingest` path keeps its current behavior; it is being retired.

Vocabulary follows the nomenclature in [`rust/ingestion-consumer/docs/driver-model.md`](../../rust/ingestion-consumer/docs/driver-model.md) §8 (#89277): **worker** (one Node.js ingestion-api process), **worker stream** (the ordered gRPC connection, never "lane"), **sub-batch** (the worker-facing unit on the wire), **batch** (one Kafka collection unit), **routing key** (`token:distinct_id`), **group** (one routing key's messages from one poll), **watermark** (the per-key acked offset), **resolve** (a send finished, success or failure).
Two sanctioned deviations where this doc touches Node code by name: the framework's `BatchingPipeline` calls one fed sub-batch a batch (so "batch" appears on framework surfaces like `BatchBudget` and `batchContext`), and "chunk" keeps its two code senses — the framework's per-stage unit (`ChunkPipeline`) and the transport's 413 body split.
"Budget" here always means this proposal's per-sub-batch **time** budget; the driver model's uncommitted-work budget `B` is a different axis and is untouched.
The proposal composes with the driver-model redesign: under it the budgeted unit becomes the request, and dispositions resolve per group — simpler there, since an unacked group returns to its key driver's queue head, and the order gate's job is what the key driver's one-release rule does by construction.

## Problem

Pipeline steps have no time limits.
A batch that hits a slow spot (a hot person merge, a degraded dependency multiplied by `retry {tries: 5}`) runs as long as it runs, and time is enforced by the _caller_ giving up:

- On the gRPC path, the consumer's ack watchdog (`INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS`, default 60 s) fences the worker stream when un-acked work makes no progress: the un-acked and queued sub-batches fail into the deferral path and re-route to another worker.
- On the HTTP path, the reqwest timeout (`HTTP_TIMEOUT_MS`, default 30 s) abandons the request, retries with `replay = true`, then defers and re-routes.

In both cases nothing tells the original worker to stop.
It keeps processing to completion — person and group writes, Kafka produces, batch-store flushes — while another worker processes the same messages.
That is duplicate downstream produce plus concurrent access to the same person rows, which is contention exactly where the pipeline was already slow.

The worker cannot do better today even if it wanted to:

- The framework has no cancellation primitive — no deadline, budget, or `AbortSignal` anywhere in `ingestion/framework/`, and the result union is closed at OK / DLQ / DROP / REDIRECT.
- The wire contract is all-or-nothing — `SubBatchAck.accepted` is meaningful only on `SUB_BATCH_STATUS_OK`, and there is no way to say "these messages finished, redeliver the rest".

## Design overview

Invert who enforces time.
The worker gets a per-sub-batch **budget**, sized by the consumer and carried on every request — the consumer owns budget policy end to end; the worker enforces what it is sent and has no sizing config of its own.
The budget carries two deadlines.
At the **soft** deadline the framework stops _starting_ work: events the budget cut off complete as a new result type, `TIMEOUT`, in-flight steps are allowed to finish, and the batch returns when they do.
At the **hard** deadline the framework stops _waiting_: still-running elements resolve `TIMEOUT` immediately, the batch settles and acks, and the stranded continuations become tracked zombies (§ soft and hard deadlines).
Events the order gate refuses to even feed (see below) complete as `REJECTED`.
The ack carries per-message dispositions so the consumer redelivers only the unfinished remainder.
The consumer sizes soft < hard < watchdog, and the watchdog stays as what it should be: a dead-worker detector.

The extension slots for this already exist:

- `SubBatchStatus` is designed for it: the consumer treats any status it does not recognize as retriable backpressure (fence in order, re-route, worker stays healthy), so a new `PARTIAL` status degrades safely for old consumers.
- `BatchingPipeline.feed(elements, batchContext)` already correlates completed batches back to their feed call (`BatchResult.batchContext`), and `CompletedSubBatch.settled` already gives per-sub-batch ack barriers.
- The consumer's dispatcher already enforces the cascade rule: once a routing key defers, its newer groups defer behind the stashed ones — which is exactly the ordering machinery redelivery needs.

### Cancellation is cooperative, at framework checkpoints

JavaScript cannot preempt a running `await`, so the framework never kills work.
At the soft deadline it stops dispatching work; at the hard deadline it stops waiting for it.
All checkpoints live in framework code; no existing step changes.

```text
server reads SubBatch frame             stamp armedAt + both budgets into the feed context
  feed(batch, ctx)                      pipeline mints the budget from its constructor
                                        factory, deadlines anchored at armedAt — so the
                                        admission wait counts
    beforeBatch hooks                   cheap, always run
    per-element chain                   raced against the hard deadline
      ◆ StepPipeline.process            soft-exhausted? → timeout, skip the step
      ◆ chunk steps                     pre-mark soft-exhausted elements timeout, run the rest
    concurrentlyPerGroup                per-key order gate → reject stale elements unfed
    hard deadline fires?                stop waiting: in-flight elements → timeout,
                                        continuations move to the zombie registry
    handleResults                       timeout/rejected: metric only, no produce
    afterBatch flush                    always runs; commits completed events' writes
  ack PARTIAL { accepted, timed_out: [indices], rejected: [indices] }
```

1. **`StepPipeline.process`** — before invoking a step on an OK result, check the element's budget.
   Exhausted → return `timeout('budget exceeded before <step>')`.
   All later steps skip automatically via the existing non-OK short-circuit.
   This one check gives per-step granularity across every per-element chain.
2. **`applyChunkStepToResults`** — chunks can mix elements from different batches with different budgets, so partition per element: exhausted OK elements become timeout and pass through; the step runs on the remainder.
   This reuses the non-OK passthrough chunk steps already honor.

Retries are deliberately not a checkpoint: the retry wrappers compose steps and see only the value, so an in-flight step runs its remaining attempts to their configured limit.
The overrun histogram measures that tail, and the hard deadline bounds it.

`TIMEOUT` and `REJECTED` both mean "not acked, redeliver" — the **unacked** results; the other four all mean "handled, do not resend".
They split by _who stopped the work_: `TIMEOUT` is the element's own budget cutting it off (mid-chain or before it started), `REJECTED` is the order gate refusing to feed an element whose processing would reorder its key — never attempted, by construction.
The consumer needs the distinction for the escalation ladder, and the metrics need it to tell slow steps (timeouts) from hot keys (rejections).
"Rejected", not "retry": both unacked results get retried — the name carries who refused, not what happens next.
An unacked element still emits a result, so `BatchingPipeline`'s count invariant holds untouched: N messages in, N results out, `afterBatch` flush still runs for the events that did finish.
An event cancelled mid-chain (after person processing, before Kafka emit) is redelivered and reprocessed from the top — the at-least-once semantics the pipeline already has, narrowed from whole fenced worker streams to the unfinished remainder.

### Soft and hard deadlines

The soft deadline is the cooperative mechanism above: stop starting, let in-flight steps finish, return when they do.
It introduces no duplication — a soft-timed-out element is not running anywhere when its redelivery processes.
Its weakness is the tail: the batch cannot return before the slowest in-flight step does (its remaining retry attempts included), and a step wedged on a dependency with no client timeout underneath holds the ack until the consumer's watchdog fences the whole stream.

The hard deadline bounds that tail.
When it fires, the framework stops waiting: still-running elements resolve `TIMEOUT` immediately, `afterBatch` flushes what completed, the ack goes out, and the admission slot is released.
The stranded continuations are not killed — JavaScript cannot — they move to a **zombie registry**, keyed by `messageId`:

- A zombie's late result is swallowed and counted, never acked and never fed to `handleResults`.
  This is what makes settling early safe where a per-step `Promise.race` (alternatives, below) was not: an orphaned resolution finds a registry entry instead of poisoning the pipeline as an unknown `messageId`.
- Batch-scoped store views stay alive until their zombies drain, but are **sealed** at settle: a zombie write after seal is dropped with a counter — correct, because the element was reported timed out and redelivery reprocesses it from the top.
- Zombies are capped.
  At the cap the worker stops admitting (`BUSY` backpressure), so a hung dependency becomes visible backpressure and a draining gauge instead of unbounded memory growth.

The honest cost: a zombie may still complete the side effects of its current step (a person write, an in-flight HTTP call) while the consumer redelivers the same event to another worker.
That is exactly the duplication the watchdog path produces today — narrowed from the whole un-acked tail to the straggler elements, and without fencing the stream.
The ladder is: **soft** (cooperative, no duplication) → **hard** (bounded per-straggler duplication, ack preserved, slot released) → **watchdog** (stream fence, whole-tail replay, dead worker).
Each rung should fire an order of magnitude less often than the one below it; the consumer sizes all three.

## Framework interface

### Budget object and results

```ts
// framework/batch-budget.ts
export class BatchBudget {
    static deadlines(softAt: number, hardAt: number | null, opts?: { enforce?: boolean }): BatchBudget
    static unlimited(): BatchBudget          // the neutral element: neither deadline exists

    readonly signal: AbortSignal             // framework-internal: fires at the SOFT
                                             //   deadline or explicit abort()
    readonly hardAt: number | null           // framework-internal: feed() races settle on it
    readonly enforce: boolean                // false = shadow mode: metrics only
    get remainingMs(): number                // to the soft deadline; Infinity when unlimited
    get exhausted(): boolean
    abort(reason?: string): void             // e.g. stream died, stop feeding its work
}

// One budget per fed batch, minted by the pipeline from its constructor factory.
export type BatchBudgetFactory<CFeed> = (batchContext: CFeed) => BatchBudget
export const unlimitedBudgetFactory: BatchBudgetFactory<unknown>

// framework/results.ts
export enum PipelineResultType { OK, DLQ, DROP, REDIRECT, TIMEOUT, REJECTED }
export function timeout<T>(reason: string): PipelineResult<T>
export function rejected<T>(reason: string): PipelineResult<T>
export function isUnackedResult(...)         // TIMEOUT or REJECTED: redeliver
```

### Budget plumbing: a mandatory constructor factory

```ts
// batching-pipeline.ts — feed() is unchanged; the budget policy is a required
// constructor option, so callers never construct or thread budgets per call
new BatchingPipeline(..., { budgetFactory: BatchBudgetFactory<CFeed> })
feed(elements, batchContext: CFeed): Promise<FeedResult>
```

The factory is **mandatory**, and can be mandatory precisely because `unlimited()` exists: there is no "no budget" state, only the unlimited budget.
The framework therefore carries no optional-budget branches — every element context always holds a budget; an unlimited one has a signal that never fires and `remainingMs() = Infinity`.
Pipelines with no time policy (tests, the non-gRPC pipelines) pass `unlimitedBudgetFactory`.

`feedSerialized` calls the factory once per fed batch and stamps the minted budget into each element's context next to `messageId`.
Sub-contexts created by `fanOut` and `filterMap` copy it the way they copy `debugContext`.
The factory receives the feed context, and the gRPC factory is a pure function of the wire: each of `soft_budget_ms` / `hard_budget_ms` maps to `0 → no deadline`, else `armedAt + budget`, with `armedAt` stamped by the server at frame read — so time parked in the admission queue counts against both deadlines even though the object is minted at feed.
There is no worker-side sizing knob for it to consult: budget policy belongs to the consumer.
Result handling treats the unacked results as a no-op (metric, no produce).

### Steps stay one-argument

Steps never see time.
`ProcessingStep<T, U, R>` remains `(value: T) => Promise<PipelineResult<U, R>>`, and enforcement lives only in the framework runners that invoke steps — `StepPipeline.process` and `applyChunkStepToResults` read the element's budget from its context and decide before the step runs.
If a slow step ever needs a per-call client deadline, that arrives as separate step-level configuration at pipeline construction, not as a signature change — out of scope here.

### `StreamIngestDriver` surface

`GrpcStreamIngestDriver` computes dispositions from the completed batch's elements (already in feed order):

```ts
export interface CompletedSubBatch {
  streamId: number
  seq: number
  accepted: number // elements.length - timedOut.length - rejected.length
  timedOut: number[] // indices into the sub-batch's messages, feed order
  rejected: number[] // never attempted: refused by the order gate
  settled: Promise<void>
}
```

`WorkerIngestServer` stamps `armedAt` and the frame's budgets into the feed context when it reads the frame — before the admission wait — and races the admission wait against the soft deadline.
One shared helper computes `armedAt + budget` for both the server's admission race and the pipeline's budget factory — no worker-side cap enters the arithmetic.
A sub-batch whose deadline passes while parked in the FIFO admission queue is acked `PARTIAL` with every message timed out, without ever being fed: nothing entered the pipeline, so no worker state exists, and the consumer redelivers through the deferral path.
The ordinary path acks after `settled` resolves: `PARTIAL` when either list is non-empty, `OK` otherwise.

## The ordering hazard, and the order gate

This is the one genuinely new invariant the ordered stream forces us to handle.

Within one sub-batch, budget exhaustion is monotone, so a routing key's completed events are always a prefix of its feed order — redelivering the suffix is safe.
Across sub-batches it is not: sub-batch N and N+1 can both be in flight with events for one routing key K (hot keys — the ones that make sub-batches slow — hit this constantly).
If N's K-events time out while N+1's K-events process (N+1's budget is younger), redelivering N's suffix would reorder the key.

The fix is a per-key **order gate** in the grouping stage, activated only for keys that produced a timeout:

- When an element of key K resolves timeout, record the **gate offset** (the offset of its first timed-out message) and the set of sub-batches currently in flight in the pipeline.
- While K is gated, an arriving K-element with offset **greater than** the gate offset is stale in-flight work — resolve it `REJECTED` without feeding it to the per-key chain (its own sub-batch acks it as rejected, and the consumer's cascade rule defers it behind K's earlier messages).
- The gate clears in either of two ways:
  - **The in-flight window drains**: every sub-batch that was in flight at gating time has completed. After that, no stale K-element can exist — the consumer holds K's newer groups behind the deferred ones until the redelivery resolves, so anything arriving later is already ordered.
  - **The redelivery returns here**: a K-element arrives with offset at or before the gate offset, restoring per-key contiguity directly.

Kafka offsets are per-partition monotone and a routing key lives on one partition, so "at or before the gate offset" is exactly "restores per-key contiguity".
The offset clause alone is not sufficient, and the window-drain clause is not an optimization: the redelivery is a deferral flush, and the dispatcher's sticky pin escapes to another worker when the pinned one is unhealthy or heavily loaded — which a budget-blowing worker often is.
The redelivery then lands elsewhere and this worker never sees an offset at or before the gate offset; without the window-drain clause it would gate fresh, correctly ordered K traffic forever, feeding a redeliver-and-gate livelock against the consumer's flush-stall bail.
The gate is generic in the framework (`concurrentlyPerGroup` gains an optional per-item sequence extractor; the analytics pipeline supplies the Kafka offset from the element context) and holds state only for gated keys.
A TTL eviction plus metric remains as a bug net, but it is not load-bearing for correctness and never needs to race `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS`.

A simpler fallback exists if the gate proves troublesome: on budget expiry, resolve every not-yet-started element in the pipeline rejected (all keys, all in-flight sub-batches — their own budgets are healthy; ordering caution, not time, stops them).
That over-cancels but needs no per-key state; the in-flight window is small.

## Wire protocol

```proto
message SubBatch {
  // ...existing fields...
  // Time allowances for processing this sub-batch, milliseconds. The worker
  // derives its budget from these fields alone; it has no sizing config of its
  // own. 0 = unlimited — which is also what a consumer predating the fields
  // sends, so compatibility is automatic. When both are set, the worker
  // requires hard_budget_ms >= soft_budget_ms; a violation is a protocol error.
  uint64 soft_budget_ms = 6;
  uint64 hard_budget_ms = 7;
}

enum SubBatchStatus {
  // ...existing values...
  // Some messages were processed and acked; the rest timed out or were rejected
  // and must be redelivered. `SubBatchAck.timed_out` and `rejected` list them.
  SUB_BATCH_STATUS_PARTIAL = 4;
}

message SubBatchAck {
  // ...existing fields...
  // Indices into SubBatch.messages the budget cut off. Set only on PARTIAL.
  repeated uint32 timed_out = 5;
  // Indices the worker never attempted: the order gate refused them to keep
  // per-key order. Set only on PARTIAL.
  repeated uint32 rejected = 6;
}
```

Both budgets are relative allowances rather than absolute deadlines, so clock skew is irrelevant; time spent on the wire and in HTTP/2 buffers stays invisible to the worker, which is why the consumer sizes both well under the watchdog (see rollout) and the watchdog remains the backstop.

Compatibility is already designed in: a consumer that predates `PARTIAL` treats it like `BUSY` — fence the worker stream in order as retriable and replay the tail — so a budget-enabled worker never corrupts an old consumer, it just wastes the partial progress.

The ack shape carries a hard invariant, validated fail-closed on the consumer: `PARTIAL` requires `timed_out` and `rejected` to be disjoint, together non-empty, and `accepted + timed_out.len() + rejected.len() == messages.len()`; `OK` requires both empty.
An ack violating any of it is a protocol error handled like `FAILED` — fence the stream and replay.
The consumer must never derive acceptance from the lists without that validation: proto3 cannot distinguish an unset list from an empty one, so trusting them would turn a worker bug into silently lost messages, where fencing turns it into a replay.

## Consumer changes

This is the largest piece outside the framework.
The stash, the cascade rule, and the ordered flush are reused as-is, but everything between the ack and the stash needs real work:

- Regenerate the proto; stamp both budgets on each `SubBatch` from new config (suggested: `INGESTION_WORKER_SUB_BATCH_SOFT_BUDGET_MS` / `_HARD_BUDGET_MS`, each default 0 = unlimited, today's semantics; when set, soft ≈ 0.5 × and hard ≈ 0.75 × `INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS`). These are the system's only budget-sizing knobs.
- **A per-message reply shape.** The transport reply today is all-or-nothing (`Accepted { accepted, messages }`), and a sub-batch the transport split into size-bounded chunks acks per chunk — the transport must remap each chunk's `timed_out` and `rejected` indices back to sub-batch positions and merge the chunk dispositions into one resolution.
- **A mixed resolve path.** Today a sub-batch resolves fully (release keys, advance counts) or fails fully (`defer_failed` stashes everything). Partial acceptance needs a resolve that releases completed messages and stashes the rest while preserving the dispatcher's outstanding-count invariants (the count nets to unchanged for stashed keys and never dips to zero mid-handoff).
- **Per-key acked watermarks computed from completed messages only.** The order sentinel advances a key's watermark using the key's maximum offset in the sub-batch; on a partial ack that would advance past unprocessed offsets and flag the redelivery as a resend-after-ack violation. The watermark must come from the completed subset.
- **An escalation ladder for events that never fit the budget.** Such an event would otherwise redeliver forever — the deferral path has no attempt cap — with each round ending in the flush-stall bail and a process restart, the watchdog fully masked. Stash entries produced by partial acks carry an attempt count; after N budget-limited attempts the message resends with both budgets 0 (unlimited), degrading to exactly today's semantics (full watchdog window, fence on overrun) for that message alone, with a counter so the pathological event is visible instead of masked.
  Only `timed_out` occurrences increment the count — a `rejected` message was never attempted, and counting it would let a hot key's gate rejections spuriously escalate its neighbors to unbudgeted resends.
  This is why the wire distinguishes the two lists at all.
- Offset commit accounting is unchanged in kind: partially accepted sub-batches hold commits exactly the way deferred groups do today, just for fewer messages.

## What this deliberately does not do

- **No forced preemption.**
  JavaScript cannot cancel a running `await`; the hard deadline forces the _return_, never the step — the stranded continuation genuinely keeps running as a zombie.
  With hard unset, worst case is soft + in-flight step tail + afterBatch flush + settled barrier; with hard set, the settle is bounded but the zombie's remaining side effects are not.
  A genuinely hung await falls to the zombie cap's backpressure, and ultimately to the ack watchdog, as today.
- **afterBatch flush is not skippable.**
  It commits completed events' person/group writes and ClickHouse rows; its duration must fit inside the margin between budget and watchdog.
- **No hard per-step timeouts.**
  Racing a timer against a stateful step orphans a continuation that later mutates shared state.
  Per-step time control lives in the framework checkpoints only, with a soft-timeout metric to surface steps that routinely exceed expectations; steps see no deadline.
- **The watchdog is narrowed, not eliminated.**
  The consumer arms each frame's ack deadline at send time, so wire time, unread-queue time behind slow predecessors, and a wedged `settled` barrier (side effects the budget cannot bound) all consume watchdog time the worker's budget never sees.
  Budgets make the fence rare; the 0.5 × sizing is margin, not proof, and the fence remains the fail-safe.

## Observability

- `ingestion_batch_budget_exhausted_total` — budgets that expired before the batch completed.
- Timeout results by last step and rejected results by key (existing `ingestion_pipeline_result` counter gains both label values) — timeouts indict slow steps, rejections indict hot keys.
- Overrun histogram — time from budget expiry to batch completion; this is the tail the checkpoints cannot cut, and the input for choosing which steps need a time policy of their own.
- Order-gate metrics — routing keys gated, stale elements gated, clears by window-drain vs offset vs TTL.
- Hard-settle metrics — hard deadlines fired, zombies outstanding (gauge), zombie late results swallowed, writes dropped after store seal, admissions refused at the zombie cap.
- Consumer side — partial acks, messages redelivered after partial, budget-exempt escalations.

Shadow mode (`enforce: false`) records all of the above without changing any result, so budgets can run in production before the first cancelled event.

## Rollout

1. **Framework** — `TIMEOUT` and `REJECTED`, `BatchBudget`, the mandatory constructor factory, the two checkpoints, metrics, shadow mode, a framework docs chapter, and stall-investigation cases for the count invariant and within-batch prefix property under budgets.
   Every existing constructor passes `unlimitedBudgetFactory`: zero behavior change, and no optional-budget code path ever exists.
2. **Order gate** — the gate/clear mechanism in `ConcurrentlyGroupingChunkPipeline` behind the sequence-extractor option, plus fuzz tests.
   Inert without budgets.
3. **Wire + worker** — proto fields, `PARTIAL` acks in `WorkerIngestServer`, dispositions in `GrpcStreamIngestDriver`, and the wire-driven budget factory; the worker's only budget knob is the shadow/enforce rollout flag (gating, not sizing).
   Run shadow in production; read the overrun and would-have-cancelled metrics.
4. **Consumer** — proto regen, budget stamping (soft only at first; hard stays 0), the per-message reply shape with chunk index remapping, the mixed resolve path, completed-only watermarks, the escalation ladder, and e2e coverage in `grpc_transport_test.rs` and the integration harness.
   Enable end to end, soft ≈ 0.5 × watchdog.
5. **Per-step time policy** — for the steps the overrun metrics indict (person merge internals, hog transformer fetches), design separate step-level configuration that derives per-call client deadlines from the batch budget without changing step signatures.
6. **Hard deadline** — the settle race, zombie registry, store sealing, and zombie-cap backpressure; enable by setting `hard_budget_ms` ≈ 0.75 × watchdog once soft-mode metrics show a real straggler tail that per-step deadlines did not cut.
   Last deliberately: every element the hard deadline saves is one the soft path plus semantic step deadlines failed to.

## Implementation plan (commit by commit)

The rollout stages above are deployment stages; this section is the review story — the sequence of commits, each one concern, each leaving the tree green (typecheck plus the touched area's tests) and the pipeline's behavior unchanged until the enforce flag turns on.
Commit subjects are fixed; a commit that cannot be built as specified is a finding to report, not a license to restructure silently.

### Phase A — framework core (commits 1–7)

Everything here is inert: no code constructs a limited budget until Phase C wires the factory to the wire fields.

1. `feat(ingestion): add timeout and rejected pipeline results`
   `results.ts` gains `TIMEOUT` and `REJECTED` members, their result types (reason-carrying, like `DROP`), the `timeout()` / `rejected()` constructors, and `isTimeoutResult` / `isRejectedResult` / `isUnackedResult` guards.
   Every exhaustive switch over the union updates in the same commit with the no-op semantics: result handling neither produces nor DLQs, and a fan-out parent becomes unacked when a sub-result is.
   Reviewable alone as: the union grows two "handled elsewhere, redeliver" members that nothing yet emits.
2. `feat(ingestion): add BatchBudget with soft and hard deadlines`
   New `batch-budget.ts` exactly per the framework interface section: `deadlines()`, `unlimited()`, the framework-internal `signal`, `hardAt`, `enforce`, `remainingMs`, `exhausted`, `abort()`, plus `BatchBudgetFactory` and `unlimitedBudgetFactory`.
   Unit tests with fake timers.
   No consumers yet.
3. `feat(ingestion): mint a budget per fed batch via a mandatory factory`
   `BatchingPipeline` constructor options gain a required `budgetFactory`; `feedSerialized` calls it once per fed batch and stamps the budget into each element's context next to `messageId`; `fanOut` / `filterMap` sub-contexts copy it like `debugContext`.
   Every existing constructor site passes `unlimitedBudgetFactory`.
   Zero behavior change; tests assert the stamp and the copy.
4. `feat(ingestion): soft-budget checkpoint in StepPipeline`
   `StepPipeline.process` checks the element's budget (from its context) before invoking a step on an OK result: exhausted → `timeout('budget exceeded before <step>')` when `enforce`, metric only in shadow.
   The step itself is invoked with one argument and sees nothing.
   Tests: mid-chain expiry short-circuits all later steps; shadow mode changes nothing.
5. `feat(ingestion): soft-budget checkpoint for chunk steps`
   `applyChunkStepToResults` partitions per element — exhausted OK elements become timeout and pass through, the step runs on the remainder — because one chunk can mix elements from batches with different budgets.
   Tests cover the mixed-budget chunk.
6. `feat(ingestion): budget observability`
   `ingestion_batch_budget_checkpoint_total`, `ingestion_batch_budget_exhausted_total`, and the overrun histogram (budget expiry → batch completion) land in `metrics.ts`, emitted from the checkpoints and from `BatchingPipeline` at batch completion, each carrying the shadow/enforce mode label.
7. `chore(ingestion): framework docs chapter and invariant cases for budgets`
   A new executable docs chapter (`18-batch-budgets.test.ts`) in the house style, plus invariant cases: the N-in/N-out count invariant under budget expiry, and the within-batch per-key prefix property.

### Phase B — order gate (commits 8–10)

8. `feat(ingestion): per-key order gate in the grouping pipeline`
   `ConcurrentlyGroupingChunkPipeline` gains the optional per-item sequence extractor and the gate: on a key's first timeout, record the gate offset and the in-flight sub-batch set; while gated, later-sequence arrivals resolve `rejected` unfed; clear on in-flight-window drain or an arrival at or before the gate offset; TTL eviction and the gate metrics as a bug net.
   Unit tests for each clear path.
9. `feat(ingestion): supply the Kafka offset as the gate sequence`
   The analytics pipeline passes the sequence extractor (offset from the element context) where it builds its grouping stage.
   Inert without budgets; the review question is only "is this the right offset".
10. `chore(ingestion): fuzz the order gate`
    Randomized interleavings of timeouts, redeliveries, and fresh traffic asserting: per-key feed order is never violated, every gate eventually clears, no rejections occur without a timeout.

### Phase C — wire and worker (commits 11–14)

11. `feat(ingestion): sub-batch budgets and PARTIAL status on the wire`
    The proto changes from the wire-protocol section verbatim (`soft_budget_ms = 6`, `hard_budget_ms = 7`, `SUB_BATCH_STATUS_PARTIAL = 4`, `timed_out = 5`, `rejected = 6`), with regenerated code per `proto/README.md`.
    Nothing reads or writes the new fields yet.
12. `feat(ingestion): stamp armedAt and wire budgets into the feed context`
    `WorkerIngestServer` stamps `armedAt` and both budget fields at frame read; one shared helper maps `0 → no deadline, else armedAt + budget`; the wire budget factory (a pure function of the feed context) replaces `unlimitedBudgetFactory` in the gRPC pipeline's construction, parameterized by the worker's shadow/enforce flag (default shadow).
13. `feat(ingestion): time out parked sub-batches at admission`
    The admission wait races the soft deadline via the shared helper; a sub-batch that expires parked acks `PARTIAL` with every message timed out, without being fed.
14. `feat(ingestion): PARTIAL acks with per-message dispositions`
    `CompletedSubBatch` gains `accepted` / `timedOut` / `rejected` computed from the completed batch's elements in feed order; the server acks `PARTIAL` when either list is non-empty after `settled`, `OK` otherwise.
    Tests assert the ack invariant from the wire-protocol section.

### Phase D — consumer (follow-up PR, commits 15–21)

This branch stays on the Node.js side; the consumer commits land in a follow-up PR.
The wire compatibility rules make the split safe: an old consumer treats `PARTIAL` as retriable `BUSY`, and the worker ships in shadow mode, where no `PARTIAL` ack is ever produced.

15. `feat(ingestion-consumer): stamp sub-batch budgets from config`
    `INGESTION_WORKER_SUB_BATCH_SOFT_BUDGET_MS` / `_HARD_BUDGET_MS` (default 0 — today's semantics), stamped on every `SubBatch`; hard < soft when both set is a startup config error.
16. `feat(ingestion-consumer): parse PARTIAL acks fail-closed`
    The ack invariant validates on receipt — disjoint lists, together non-empty, `accepted + timed_out.len() + rejected.len() == messages.len()`, `OK` requires both empty; violations handle like `FAILED`.
    A valid `PARTIAL` temporarily takes the existing retriable path (what an old consumer does), so this commit is safe before the mixed resolve exists.
17. `feat(ingestion-consumer): remap chunk dispositions to sub-batch indices`
    The transport's per-message reply shape replaces all-or-nothing acceptance: each 413-split chunk's `timed_out` / `rejected` indices remap to sub-batch positions and merge into one resolution.
18. `feat(ingestion-consumer): mixed resolve — release completed, stash the remainder`
    The dispatcher resolves a partial ack by releasing completed messages and stashing the rest, preserving the outstanding-count invariants (net unchanged for stashed keys, never zero mid-handoff); the cascade rule then defers newer groups behind the stash as today.
19. `feat(ingestion-consumer): advance watermarks from completed messages only`
    The order sentinel computes a key's watermark from the completed subset of a partial ack, so redelivery of the remainder is not a resend-after-ack violation.
20. `feat(ingestion-consumer): escalate never-fitting events to unbudgeted resends`
    Stash entries from partial acks carry an attempt count; only `timed_out` occurrences increment it; after N budget-limited attempts the message resends with both budgets 0, with a counter.
21. `chore(ingestion-consumer): e2e coverage for partial acks`
    `grpc_transport_test.rs` and the integration harness: partial ack → redelivery → completion, hot-key ordering preserved across partial acks, the escalation path.

### Phase E — hard deadline (commits 22–23)

22. `feat(ingestion): race batch settle against the hard deadline`
    When `hardAt` is set, `feed()` races settle on it: still-running elements resolve timeout, `afterBatch` flushes what completed, the ack goes out, and stranded continuations move to the zombie registry keyed by `messageId` — late results are swallowed and counted, never acked.
23. `feat(ingestion): seal batch stores at settle and cap zombies`
    Batch-scoped store views seal at settle (late writes dropped with a counter) and stay alive until their zombies drain; at the zombie cap the worker stops admitting (`BUSY`), with the outstanding-zombies gauge and the hard-settle metrics.

Out of scope for this branch: the consumer (Phase D, a follow-up PR), a per-step time policy (rollout stage 5 — driven by production overrun metrics), and any production config enabling budgets.

## Alternatives considered

- **Hard abort via `Promise.race` per step** — rejected in that form.
  The losing promise keeps running with batch-bound store views; its late completion corrupts `BatchingPipeline` bookkeeping (unknown `messageId` → poisoned pipeline → server suicide) and recreates concurrent double-processing inside one process.
  The hard deadline keeps the race but moves it to the one place it is safe — batch settle — with a zombie registry to receive late resolutions and sealed stores to drop late writes.
- **Respond partial and let the whole batch keep running in the background** — rejected: the admission slot leaks and the original problem returns in-process wholesale.
  The hard deadline differs on both counts: the soft deadline already stopped dispatch, so only mid-await stragglers survive settle, and the zombie cap converts pileup into backpressure instead of a leak.
- **Rely on the watchdog fence alone (status quo)** — rejected: fencing replays the whole un-acked tail while the worker keeps working, which is the duplication and contention this proposal removes.
- **Absolute deadlines on the wire instead of `budget_ms`** — rejected: clock skew between consumer and worker turns into silent budget errors; a relative allowance armed at frame read is skew-free, and the watchdog already covers wire-time blindness.
- **Cancel only at sub-batch boundaries (no mid-batch checkpoints)** — rejected: a single slow event would still pin the whole sub-batch until it finishes, which under a 60 s watchdog is precisely the current failure mode.
