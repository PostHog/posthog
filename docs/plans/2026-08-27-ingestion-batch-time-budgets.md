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
The worker gets a per-sub-batch **budget** sized so it acks well before the consumer's watchdog fires.
When the budget expires, the framework stops _starting_ work: events the budget cut off complete as a new result type, `TIMEOUT`; events the order gate refuses to even feed (see below) complete as `REJECTED`; and the ack carries per-message dispositions so the consumer redelivers only the unfinished remainder.
The watchdog stays as what it should be: a dead-worker detector.

The extension slots for this already exist:

- `SubBatchStatus` is designed for it: the consumer treats any status it does not recognize as retriable backpressure (fence in order, re-route, worker stays healthy), so a new `PARTIAL` status degrades safely for old consumers.
- `BatchingPipeline.feed(elements, batchContext)` already correlates completed batches back to their feed call (`BatchResult.batchContext`), and `CompletedSubBatch.settled` already gives per-sub-batch ack barriers.
- The consumer's dispatcher already enforces the cascade rule: once a routing key defers, its newer groups defer behind the stashed ones — which is exactly the ordering machinery redelivery needs.

### Cancellation is cooperative, at framework checkpoints

JavaScript cannot preempt a running `await`, and racing a timer against a stateful step leaves a zombie continuation that later mutates shared stores — the same duplication problem, moved in-process.
So the framework never kills work; it stops dispatching it.
All checkpoints live in framework code; no existing step changes.

```text
server reads SubBatch frame             stamp armedAt + budget_ms into the feed context
  feed(batch, ctx)                      pipeline mints the budget from its constructor
                                        factory, deadline anchored at armedAt — so the
                                        admission wait counts
    beforeBatch hooks                   cheap, always run
    per-element chain
      ◆ StepPipeline.process            exhausted? → timeout, skip the step
      ◆ chunk steps                     pre-mark exhausted elements timeout, run the rest
      ◆ withStepRetry / withChunkRetry  signal fired? stop retrying → timeout
    concurrentlyPerGroup                per-key order gate → reject stale elements unfed
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
3. **`withStepRetry` / `withChunkRetry`** — check the signal before each backoff sleep.
   Budget gone → return timeout instead of burning retries.
   This bounds the post-budget tail to roughly one attempt of the slowest step instead of five.

`TIMEOUT` and `REJECTED` both mean "not acked, redeliver" — the **unacked** results; the other four all mean "handled, do not resend".
They split by _who stopped the work_: `TIMEOUT` is the element's own budget cutting it off (mid-chain or before it started), `REJECTED` is the order gate refusing to feed an element whose processing would reorder its key — never attempted, by construction.
The consumer needs the distinction for the escalation ladder, and the metrics need it to tell slow steps (timeouts) from hot keys (rejections).
"Rejected", not "retry": both unacked results get retried — the name carries who refused, not what happens next.
An unacked element still emits a result, so `BatchingPipeline`'s count invariant holds untouched: N messages in, N results out, `afterBatch` flush still runs for the events that did finish.
An event cancelled mid-chain (after person processing, before Kafka emit) is redelivered and reprocessed from the top — the at-least-once semantics the pipeline already has, narrowed from whole fenced worker streams to the unfinished remainder.

## Framework interface

### Budget object and results

```ts
// framework/batch-budget.ts
export class BatchBudget {
    static deadline(at: number, opts?: { enforce?: boolean }): BatchBudget
    static unlimited(): BatchBudget          // the neutral element: never expires

    readonly signal: AbortSignal             // fires at the deadline or explicit abort()
    readonly enforce: boolean                // false = shadow mode: metrics only
    get remainingMs(): number                // Infinity when unlimited
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
The factory receives the feed context, and the analytics factory anchors its deadline at the `armedAt` the server stamped at frame read — so time parked in the admission queue counts against the budget even though the object is minted at feed.
Result handling treats the unacked results as a no-op (metric, no produce); ingestion-warning handling and TopHog gain both new result labels.

### Steps: backward-compatible opt-in

Steps gain an optional second parameter.
Every existing single-argument step stays assignable; slow steps (person merge internals, hog transformer fetches) adopt the signal over time and can derive per-call client deadlines from `remainingMs()`.

```ts
export interface StepContext {
  signal: AbortSignal // never-aborting when unlimited
  remainingMs(): number
}
export type ProcessingStep<T, U, R extends string = never> = (
  value: T,
  ctx: StepContext
) => Promise<PipelineResult<U, R>>
```

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

`WorkerIngestServer` stamps `armedAt` and the frame's `budget_ms` into the feed context when it reads the frame — before the admission wait — and races the admission wait against the same deadline.
One shared helper computes `armedAt + min(budget_ms, cap)` for both the server's admission race and the pipeline's budget factory, so the sizing policy lives once.
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
  // Time allowance for processing this sub-batch, milliseconds; 0 = no budget.
  // The worker takes min(budget_ms, its own configured cap).
  uint64 budget_ms = 6;
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

`budget_ms` is a relative allowance rather than an absolute deadline, so clock skew is irrelevant; time spent on the wire and in HTTP/2 buffers stays invisible to the worker, which is why the consumer sizes the budget well under the watchdog (see rollout) and the watchdog remains the backstop.

Compatibility is already designed in: a consumer that predates `PARTIAL` treats it like `BUSY` — fence the worker stream in order as retriable and replay the tail — so a budget-enabled worker never corrupts an old consumer, it just wastes the partial progress.

The ack shape carries a hard invariant, validated fail-closed on the consumer: `PARTIAL` requires `timed_out` and `rejected` to be disjoint, together non-empty, and `accepted + timed_out.len() + rejected.len() == messages.len()`; `OK` requires both empty.
An ack violating any of it is a protocol error handled like `FAILED` — fence the stream and replay.
The consumer must never derive acceptance from the lists without that validation: proto3 cannot distinguish an unset list from an empty one, so trusting them would turn a worker bug into silently lost messages, where fencing turns it into a replay.

## Consumer changes

This is the largest piece outside the framework.
The stash, the cascade rule, and the ordered flush are reused as-is, but everything between the ack and the stash needs real work:

- Regenerate the proto; stamp `budget_ms` on each `SubBatch` from new config (suggested: `INGESTION_WORKER_SUB_BATCH_BUDGET_MS`, default 0 = disabled; when set, sized at roughly half `INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS`).
- **A per-message reply shape.** The transport reply today is all-or-nothing (`Accepted { accepted, messages }`), and a sub-batch the transport split into size-bounded chunks acks per chunk — the transport must remap each chunk's `timed_out` and `rejected` indices back to sub-batch positions and merge the chunk dispositions into one resolution.
- **A mixed resolve path.** Today a sub-batch resolves fully (release keys, advance counts) or fails fully (`defer_failed` stashes everything). Partial acceptance needs a resolve that releases completed messages and stashes the rest while preserving the dispatcher's outstanding-count invariants (the count nets to unchanged for stashed keys and never dips to zero mid-handoff).
- **Per-key acked watermarks computed from completed messages only.** The order sentinel advances a key's watermark using the key's maximum offset in the sub-batch; on a partial ack that would advance past unprocessed offsets and flag the redelivery as a resend-after-ack violation. The watermark must come from the completed subset.
- **An escalation ladder for events that never fit the budget.** Such an event would otherwise redeliver forever — the deferral path has no attempt cap — with each round ending in the flush-stall bail and a process restart, the watchdog fully masked. Stash entries produced by partial acks carry an attempt count; after N budget-limited attempts the message resends with `budget_ms = 0`, degrading to exactly today's semantics (full watchdog window, fence on overrun) for that message alone, with a counter so the pathological event is visible instead of masked.
  Only `timed_out` occurrences increment the count — a `rejected` message was never attempted, and counting it would let a hot key's gate rejections spuriously escalate its neighbors to `budget_ms = 0`.
  This is why the wire distinguishes the two lists at all.
- Offset commit accounting is unchanged in kind: partially accepted sub-batches hold commits exactly the way deferred groups do today, just for fewer messages.

## What this deliberately does not do

- **No forced preemption.**
  Worst case is budget + in-flight step tail + afterBatch flush + settled barrier, not an exact cutoff.
  A genuinely hung await (no client timeout underneath) still falls to the ack watchdog, as today.
- **afterBatch flush is not skippable.**
  It commits completed events' person/group writes and ClickHouse rows; its duration must fit inside the margin between budget and watchdog.
- **No hard per-step timeouts.**
  Racing a timer against a stateful step orphans a continuation that later mutates shared state.
  Per-step time control is cooperative only: the signal, plus a soft-timeout metric to surface steps that routinely exceed expectations.
- **The watchdog is narrowed, not eliminated.**
  The consumer arms each frame's ack deadline at send time, so wire time, unread-queue time behind slow predecessors, and a wedged `settled` barrier (side effects the budget cannot bound) all consume watchdog time the worker's budget never sees.
  Budgets make the fence rare; the 0.5 × sizing is margin, not proof, and the fence remains the fail-safe.

## Observability

- `ingestion_batch_budget_exhausted_total` — budgets that expired before the batch completed.
- Timeout results by last step and rejected results by key (existing `ingestion_pipeline_result` counter gains both label values) — timeouts indict slow steps, rejections indict hot keys.
- Overrun histogram — time from budget expiry to batch completion; this is the tail the checkpoints cannot cut, and the input for choosing which steps adopt the signal.
- Order-gate metrics — routing keys gated, stale elements gated, clears by window-drain vs offset vs TTL.
- Consumer side — partial acks, messages redelivered after partial, budget-exempt escalations.

Shadow mode (`enforce: false`) records all of the above without changing any result, so budgets can run in production before the first cancelled event.

## Rollout

1. **Framework** — `TIMEOUT` and `REJECTED`, `BatchBudget`, the mandatory constructor factory, the three checkpoints, retry integration, metrics, shadow mode, a framework docs chapter, and stall-investigation cases for the count invariant and within-batch prefix property under budgets.
   Every existing constructor passes `unlimitedBudgetFactory`: zero behavior change, and no optional-budget code path ever exists.
2. **Order gate** — the gate/clear mechanism in `ConcurrentlyGroupingChunkPipeline` behind the sequence-extractor option, plus fuzz tests.
   Inert without budgets.
3. **Wire + worker** — proto fields, `PARTIAL` acks in `WorkerIngestServer`, dispositions in `GrpcStreamIngestDriver`, worker-side cap config.
   Run shadow in production; read the overrun and would-have-cancelled metrics.
4. **Consumer** — proto regen, `budget_ms` stamping, the per-message reply shape with chunk index remapping, the mixed resolve path, completed-only watermarks, the escalation ladder, and e2e coverage in `grpc_transport_test.rs` and the integration harness.
   Enable end to end, budget ≈ 0.5 × watchdog.
5. **Step adoption** — thread `StepContext.signal` into the steps the overrun metrics indict (person merge internals, hog transformer fetches); derive per-call deadlines from `remainingMs()`.

## Alternatives considered

- **Hard abort via `Promise.race` per step** — rejected.
  The losing promise keeps running with batch-bound store views; its late completion corrupts `BatchingPipeline` bookkeeping (unknown `messageId` → poisoned pipeline → server suicide) and recreates concurrent double-processing inside one process.
- **Respond partial but let the batch keep running in the background** — rejected for the same reason: the admission slot leaks and the original problem returns in-process.
- **Rely on the watchdog fence alone (status quo)** — rejected: fencing replays the whole un-acked tail while the worker keeps working, which is the duplication and contention this proposal removes.
- **Absolute deadlines on the wire instead of `budget_ms`** — rejected: clock skew between consumer and worker turns into silent budget errors; a relative allowance armed at frame read is skew-free, and the watchdog already covers wire-time blindness.
- **Cancel only at sub-batch boundaries (no mid-batch checkpoints)** — rejected: a single slow event would still pin the whole sub-batch until it finishes, which under a 60 s watchdog is precisely the current failure mode.
