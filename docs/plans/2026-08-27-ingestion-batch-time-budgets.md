# Ingestion batch time budgets and partial completion

Status: proposal.
Scope: the Node.js ingestion pipelines framework (`nodejs/src/ingestion/framework/`), the WorkerIngest gRPC transport, and the Rust ingestion consumer's handling of partial acks.
The HTTP `/ingest` path keeps its current behavior; it is being retired.

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
The worker gets a per-sub-batch **budget** and always acks before the consumer's watchdog would fire.
When the budget expires, the framework stops _starting_ work: events not yet processed complete as a new result type, `INCOMPLETE`, and the ack carries per-message dispositions so the consumer redelivers only the unfinished remainder.
The watchdog stays as what it should be: a dead-worker detector.

The extension slots for this already exist:

- `SubBatchStatus` is designed for it: the consumer treats any status it does not recognize as retriable backpressure (fence in order, re-route, worker stays healthy), so a new `PARTIAL` status degrades safely for old consumers.
- `BatchingPipeline.feed(elements, batchContext)` already correlates completed batches back to their feed call (`BatchResult.batchContext`), and `CompletedSubBatch.settled` already gives per-batch ack barriers.
- The consumer's dispatcher already cascade-defers: a key with deferred groups pending gets its newer messages queued behind them, which is exactly the ordering machinery redelivery needs.

### Cancellation is cooperative, at framework checkpoints

JavaScript cannot preempt a running `await`, and racing a timer against a stateful step leaves a zombie continuation that later mutates shared stores — the same duplication problem, moved in-process.
So the framework never kills work; it stops dispatching it.
All checkpoints live in framework code; no existing step changes.

```text
server reads SubBatch frame             arm BatchBudget (admission wait counts)
  feed(batch, ctx, { budget })          stamp budget into each element's context
    beforeBatch hooks                   cheap, always run
    per-element chain
      ◆ StepPipeline.process            exhausted? → incomplete, skip the step
      ◆ chunk steps                     pre-mark exhausted elements, run the rest
      ◆ withStepRetry / withChunkRetry  signal fired? stop retrying → incomplete
    concurrentlyPerGroup                order gate for poisoned keys (see below)
    handleResults                       incomplete: metric only, no produce
    afterBatch flush                    always runs; commits completed events' writes
  ack PARTIAL { accepted, incomplete: [indices] }
```

1. **`StepPipeline.process`** — before invoking a step on an OK result, check the element's budget.
   Exhausted → return `incomplete('budget exceeded before <step>')`.
   All later steps skip automatically via the existing non-OK short-circuit.
   This one check gives per-step granularity across every per-element chain.
2. **`applyChunkStepToResults`** — chunks can mix elements from different batches with different budgets, so partition per element: exhausted OK elements become incomplete and pass through; the step runs on the remainder.
   This reuses the non-OK passthrough chunk steps already honor.
3. **`withStepRetry` / `withChunkRetry`** — check the signal before each backoff sleep.
   Budget gone → return incomplete instead of burning retries.
   This bounds the post-budget tail to roughly one attempt of the slowest step instead of five.

`INCOMPLETE` means "not acked, redeliver"; the other four results all mean "handled, do not resend".
An incomplete element still emits a result, so `BatchingPipeline`'s count invariant holds untouched: N messages in, N results out, `afterBatch` flush still runs for the events that did finish.
An event cancelled mid-chain (after person processing, before Kafka emit) is redelivered and reprocessed from the top — the at-least-once semantics the pipeline already has, narrowed from whole fenced lanes to the unfinished remainder.

## Framework interface

### Budget object and results

```ts
// framework/batch-budget.ts
export class BatchBudget {
    static timeout(ms: number, opts?: { enforce?: boolean }): BatchBudget
    static unlimited(): BatchBudget          // default everywhere; zero behavior change

    readonly signal: AbortSignal             // fires at the deadline or explicit abort()
    readonly enforce: boolean                // false = shadow mode: metrics only
    get remainingMs(): number                // Infinity when unlimited
    get exhausted(): boolean
    abort(reason?: string): void             // e.g. stream died, stop feeding its work
}

// framework/results.ts
export enum PipelineResultType { OK, DLQ, DROP, REDIRECT, INCOMPLETE }
export function incomplete<T>(reason: string): PipelineResult<T>
export function isIncompleteResult(...)
```

### Feed plumbing

```ts
// batching-pipeline.ts — third parameter alongside the existing CFeed context
feed(elements, batchContext: CFeed, options?: { budget?: BatchBudget }): Promise<FeedResult>
```

`feedSerialized` stamps the budget into each element's context next to `messageId`.
Sub-contexts created by `fanOut` and `filterMap` copy it the way they copy `debugContext`.
Result handling treats incomplete as a no-op (metric, no produce); ingestion-warning handling and TopHog gain the new result label.

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

### Driver surface

`GrpcStreamIngestDriver` computes dispositions from the completed batch's elements (already in feed order):

```ts
export interface CompletedSubBatch {
  streamId: number
  seq: number
  accepted: number // elements.length - incomplete.length
  incomplete: number[] // indices into the sub-batch's messages, feed order
  settled: Promise<void>
}
```

`WorkerIngestServer` creates the `BatchBudget` when it reads the frame — before the admission wait — so a sub-batch that spends its life parked in the FIFO admission queue surfaces as an ordered `PARTIAL` (everything incomplete, redelivered cleanly) instead of a watchdog fence.
It acks `PARTIAL` when `incomplete` is non-empty, `OK` otherwise.

## The ordering hazard, and the order gate

This is the one genuinely new invariant the ordered stream forces us to handle.

Within one sub-batch, budget exhaustion is monotone, so a key's completed events are always a prefix of its feed order — redelivering the suffix is safe.
Across sub-batches it is not: sub-batch N and N+1 can both be in flight with events for key K (hot keys — the ones that make batches slow — hit this constantly).
If N's K-events go incomplete while N+1's K-events process (N+1's budget is younger), redelivering N's suffix would reorder the key.

The fix is a per-key **order gate** in the grouping stage, activated only for keys that produced an incomplete result:

- When an element of key K resolves incomplete, record `poison[K] = offset of its first incomplete message`.
- While poisoned, an arriving K-element with offset **greater than** the poison point is stale in-flight work — resolve it incomplete without processing (its own sub-batch acks it as incomplete, and the consumer's cascade-deferral queues it behind K's earlier messages).
- An arriving K-element with offset **at or before** the poison point is the redelivery (or a full replay after a reconnect) — clear the poison and process normally.

Kafka offsets are per-partition monotone and a key lives on one partition, so "at or before the poison point" is exactly "restores per-key contiguity".
The stream's ordering guarantees make the rule airtight: everything fed between the poisoning and the redelivery was sent before the consumer learned of it, and the redelivery necessarily arrives after.
The gate is generic in the framework (`concurrentlyPerGroup` gains an optional per-item sequence extractor; the analytics pipeline supplies the Kafka offset from the element context) and holds state only for poisoned keys, with a TTL eviction plus metric as a safety net for redeliveries that never come.

A simpler fallback exists if the gate proves troublesome: on budget expiry, cancel every not-yet-started element in the pipeline (all keys, all in-flight sub-batches).
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
  // Some messages were processed and acked; the rest were not started (or not
  // finished) and must be redelivered. `SubBatchAck.incomplete` lists them.
  SUB_BATCH_STATUS_PARTIAL = 4;
}

message SubBatchAck {
  // ...existing fields...
  // Indices into SubBatch.messages that were not processed. Set only on PARTIAL.
  repeated uint32 incomplete = 5;
}
```

`budget_ms` is a relative allowance rather than an absolute deadline, so clock skew is irrelevant; time spent on the wire and in HTTP/2 buffers stays invisible to the worker, which is why the consumer sizes the budget well under the watchdog (see rollout) and the watchdog remains the backstop.

Compatibility is already designed in: a consumer that predates `PARTIAL` treats it like `BUSY` — fence the lane in order as retriable and replay the tail — so a budget-enabled worker never corrupts an old consumer, it just wastes the partial progress.

## Consumer changes

- Regenerate the proto; stamp `budget_ms` on each `SubBatch` from new config (suggested: `INGESTION_WORKER_BATCH_BUDGET_MS`, default 0 = disabled; when set, sized at roughly half `INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS`).
- `handle_ack` on `PARTIAL`: resolve the ledger entry with per-message dispositions — completed messages count as accepted, incomplete messages go into the existing per-batch stash (the `defer_failed` path, but for a subset).
  The dispatcher's cascade-deferral already queues the key's newer messages behind them, and `flush_deferred` already replays in order with `replay = true`, which the feed-order sentinel already tolerates.
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

## Observability

- `ingestion_batch_budget_exhausted_total` — budgets that expired before the batch completed.
- Incomplete results by last step (existing `ingestion_pipeline_result` counter gains the label value).
- Overrun histogram — time from budget expiry to batch completion; this is the tail the checkpoints cannot cut, and the input for choosing which steps adopt the signal.
- Order-gate metrics — keys poisoned, stale elements gated, poison evictions by TTL.
- Consumer side — partial acks, messages redelivered after partial.

Shadow mode (`enforce: false`) records all of the above without changing any result, so budgets can run in production before the first cancelled event.

## Rollout

1. **Framework** — `INCOMPLETE`, `BatchBudget`, feed plumbing, the three checkpoints, retry integration, metrics, shadow mode, a framework docs chapter, and stall-investigation cases for the count invariant and within-batch prefix property under budgets.
   Default `unlimited()`: zero behavior change.
2. **Order gate** — the poison/clear mechanism in `ConcurrentlyGroupingChunkPipeline` behind the sequence-extractor option, plus fuzz tests.
   Inert without budgets.
3. **Wire + worker** — proto fields, `PARTIAL` acks in `WorkerIngestServer`, dispositions in `GrpcStreamIngestDriver`, worker-side cap config.
   Run shadow in production; read the overrun and would-have-cancelled metrics.
4. **Consumer** — proto regen, `budget_ms` stamping, `PARTIAL` handling into the stash, e2e coverage in `grpc_transport_test.rs` and the integration harness.
   Enable end to end, budget ≈ 0.5 × watchdog.
5. **Step adoption** — thread `StepContext.signal` into the steps the overrun metrics indict (person merge internals, hog transformer fetches); derive per-call deadlines from `remainingMs()`.

## Alternatives considered

- **Hard abort via `Promise.race` per step** — rejected.
  The losing promise keeps running with batch-bound store views; its late completion corrupts `BatchingPipeline` bookkeeping (unknown `messageId` → poisoned pipeline → server suicide) and recreates concurrent double-processing inside one process.
- **Respond partial but let the batch keep running in the background** — rejected for the same reason: the admission slot leaks and the original problem returns in-process.
- **Rely on the watchdog fence alone (status quo)** — rejected: fencing replays the whole un-acked tail while the worker keeps working, which is the duplication and contention this proposal removes.
- **Absolute deadlines on the wire instead of `budget_ms`** — rejected: clock skew between consumer and worker turns into silent budget errors; a relative allowance armed at frame read is skew-free, and the watchdog already covers wire-time blindness.
- **Cancel only at sub-batch boundaries (no mid-batch checkpoints)** — rejected: a single slow event would still pin the whole sub-batch until it finishes, which under a 60 s watchdog is precisely the current failure mode.
