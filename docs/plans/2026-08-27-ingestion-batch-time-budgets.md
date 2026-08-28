# Ingestion batch time budgets and partial completion

Status: worker side implemented on this branch; consumer side is a follow-up PR.
Scope: the Node.js ingestion pipelines framework (`nodejs/src/ingestion/framework/`), the WorkerIngest gRPC transport, and the Rust ingestion consumer's handling of partial acks.
The HTTP `/ingest` path keeps its current behavior; it is being retired.

Vocabulary follows the nomenclature in [`rust/ingestion-consumer/docs/driver-model.md`](../../rust/ingestion-consumer/docs/driver-model.md) §8 (#89277): **worker** (one Node.js ingestion-api process), **worker stream** (the ordered gRPC connection, never "lane"), **sub-batch** (the worker-facing unit on the wire), **batch** (one Kafka collection unit), **routing key** (`token:distinct_id`), **group** (one routing key's messages from one poll), **watermark** (the per-key acked offset), **resolve** (a send finished, success or failure).
Two sanctioned deviations where this doc touches Node code by name: the framework's `BatchingPipeline` calls one fed sub-batch a batch (so "batch" appears on framework surfaces like `BatchBudget` and `batchContext`), and "chunk" keeps its two code senses — the framework's per-stage unit (`ChunkPipeline`) and the transport's 413 body split.
"Budget" here always means this proposal's per-sub-batch **time** budget; the driver model's uncommitted-work budget `B` is a different axis and is untouched.
The proposal composes with the driver-model redesign: under it the budgeted unit becomes the request, and dispositions resolve per group — simpler there, since an unacked group returns to its key driver's queue head, and the key driver's one-release rule provides the per-key ordering precondition (§ the ordering hazard) by construction.

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
The worker gets a per-sub-batch **budget**, sized by the consumer and carried on every request — the consumer owns budget policy end to end; the worker enforces what it is sent and has no budget config of its own.
The budget carries one deadline, and it is deliberately **soft**.
At it the framework stops _starting_ work: events the budget cut off complete as a new result type, `TIMEOUT`, in-flight steps are allowed to finish, and the batch returns when they do (§ the soft deadline and the watchdog).
The ack carries per-message dispositions so the consumer redelivers only the unfinished remainder.
The consumer sizes the budget well under its ack watchdog, and the watchdog stays what it should be: the system's one hard limit and its dead-worker detector.

The extension slots for this already exist:

- `SubBatchStatus` is designed for it: the consumer treats any status it does not recognize as retriable backpressure (fence in order, re-route, worker stays healthy), so a new `PARTIAL` status degrades safely for old consumers.
- `BatchingPipeline.feed(elements, batchContext)` already correlates completed batches back to their feed call (`BatchResult.batchContext`), and `CompletedSubBatch.settled` already gives per-sub-batch ack barriers.
- The consumer's dispatcher already enforces the cascade rule: once a routing key defers, its newer groups defer behind the stashed ones — which is exactly the ordering machinery redelivery needs.

### Cancellation is cooperative, at framework checkpoints

JavaScript cannot preempt a running `await`, so the framework never kills work.
At the soft deadline it stops dispatching work; work already dispatched finishes.
All checkpoints live in framework code; no existing step changes.

```text
server reads SubBatch frame             stamp armedAt; hand the allowance to the driver
  feed(batch, ctx, budget)              the driver builds the budget, deadline anchored
                                        at armedAt — so the admission wait counts
    beforeBatch hooks                   cheap, always run
    per-element chain
      ◆ StepPipeline.process            soft-exhausted? → timeout, skip the step
      ◆ chunk steps                     pre-mark soft-exhausted elements timeout, run the rest
    handleResults                       timeout: metric only, no produce
    afterBatch flush                    always runs; commits completed events' writes
  ack PARTIAL { accepted, timed_out: [indices] }
```

1. **`StepPipeline.process`** — before invoking a step on an OK result, check the element's budget.
   Exhausted → return `timeout('budget exceeded before <step>')`.
   All later steps skip automatically via the existing non-OK short-circuit.
   This one check gives per-step granularity across every per-element chain.
2. **`applyChunkStepToResults`** — chunks can mix elements from different batches with different budgets, so partition per element: exhausted OK elements become timeout and pass through; the step runs on the remainder.
   This reuses the non-OK passthrough chunk steps already honor.

Retries are deliberately not a checkpoint: the retry wrappers compose steps and see only the value, so an in-flight step runs its remaining attempts to their configured limit.
The overrun histogram measures that tail, and the watchdog bounds it.

`TIMEOUT` means "not acked, redeliver" — the one **unacked** result; the other four all mean "handled, do not resend".
A timed-out element still emits a result, so `BatchingPipeline`'s count invariant holds untouched: N messages in, N results out, `afterBatch` flush still runs for the events that did finish.
An event cancelled mid-chain (after person processing, before Kafka emit) is redelivered and reprocessed from the top — the at-least-once semantics the pipeline already has, narrowed from whole fenced worker streams to the unfinished remainder.

### The soft deadline and the watchdog

The soft deadline is the cooperative mechanism above: stop starting, let in-flight steps finish, return when they do.
It introduces no duplication — a soft-timed-out element is not running anywhere when its redelivery processes.
Its tail is the slowest in-flight step (remaining retry attempts included): the batch cannot return before that step does.

That tail is acceptable because of what makes batches slow in practice: not one expensive event, but many cheap events processed sequentially.
Step-duration tails are short and uncorrelated with lag, so cutting off _new_ work is what recovers a lagging batch; the rare step wedged on a dependency with no client timeout underneath holds the ack until the consumer's watchdog fences the stream — exactly as it does today, and rarely enough that the fence stays a fail-safe rather than a mechanism.

The ladder is two rungs: **soft budget** (worker-enforced, cooperative, no duplication) → **watchdog** (consumer-enforced stream fence, whole-tail replay — the system's one hard limit).
A worker-side hard deadline between the rungs was designed, implemented, and dropped (§ alternatives considered).

## Framework interface

### Budget object and results

```ts
// framework/batch-budget.ts
export class BatchBudget {
    static softDeadline(softAt: number): BatchBudget
    static unlimited(): BatchBudget          // shared singleton: the neutral element, never exhausts

    readonly softAt: number                  // Infinity when unlimited
    get exhausted(): boolean                 // a field read; an internal timer flips it at softAt
    settle(): void                           // clears the timer at batch completion
}

// framework/results.ts
export enum PipelineResultType { OK, DLQ, DROP, REDIRECT, TIMEOUT }
export function timeout<T>(reason: string): PipelineResult<T>
export function isTimeoutResult(...)         // not acked: redeliver
```

### A budget per feed

```ts
// batching-pipeline.ts — the budget is per-batch data, so it rides the feed call
feed(elements, batchContext: CFeed, budget: BatchBudget = BatchBudget.unlimited()): Promise<FeedResult>
```

The argument defaults to the unlimited budget, so there is no "no budget" state, only the unlimited budget.
The framework therefore carries no optional-budget branches — every element context always holds a budget; an unlimited one never exhausts.
A budget enforces by virtue of existing: there is no worker-side gating flag, and no shadow mode — the consumer decides by sending `soft_budget_ms` or 0.
Callers with no time policy (tests, the non-gRPC pipelines) pass nothing.

`feedSerialized` stamps the fed budget into each element's context next to `messageId`.
Sub-contexts created by `fanOut` and `filterMap` copy it the way they copy `debugContext`.
The gRPC driver builds the budget at its feed call as a pure function of the wire: `soft_budget_ms` maps to `0 → unlimited`, else a soft deadline at `armedAt + budget`, with `armedAt` stamped by the server at frame read — so time parked in the admission queue counts against the deadline.
There is no worker-side sizing knob: budget policy belongs to the consumer.
Result handling treats a timeout as a no-op (metric, no produce).

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
  accepted: number // elements.length - timedOut.length
  timedOut: number[] // indices into the sub-batch's messages, feed order
  settled: Promise<void>
}
```

`WorkerIngestServer` stamps `armedAt` when it reads the frame — before the admission wait — races the admission wait against the soft deadline, and hands the wire allowance to the driver's feed.
One shared helper computes `armedAt + budget` for both the server's admission race and the driver's budget construction — no worker-side cap enters the arithmetic.
A sub-batch whose deadline passes while parked in the FIFO admission queue is acked `PARTIAL` with every message timed out, without ever being fed: nothing entered the pipeline, so no worker state exists, and the consumer redelivers through the deferral path.
The ordinary path acks after `settled` resolves: `PARTIAL` when `timed_out` is non-empty, `OK` otherwise.

## The ordering hazard

This is the one genuinely new invariant budgets disturb, and this design assigns it to the consumer rather than defending on the worker.

Within one sub-batch, budget exhaustion is monotone, so a routing key's completed events are always a prefix of its feed order — redelivering the suffix is safe.
Across sub-batches it is not: sub-batch N and N+1 can both be in flight with events for one routing key K (hot keys — the ones that make sub-batches slow — hit this constantly).
If N's K-events time out while N+1's K-events process (N+1's budget is younger), redelivering N's suffix reorders the key: the redelivered older event runs after the newer one, and its writes win.

The worker does not defend against this.
An earlier revision carried a worker-side per-key order gate (a sequence extractor on the grouping stage, gating and clearing per key); it was dropped for interface simplicity, because per-key order is the consumer's guarantee everywhere else in this system and a worker-side gate duplicates it.
What remains is a **precondition for enforcement**: budgets stay unsent (`soft_budget_ms = 0`) until the consumer never keeps two in-flight sub-batches carrying the same routing key, or the operator explicitly accepts hot-key reordering.
The dispatcher's existing stash-and-cascade machinery is close to what a "hold a key's newer groups while it has unacked messages" rule needs; under the driver-model redesign the key driver's one-release rule provides exactly this by construction, and the precondition dissolves.

## Wire protocol

```proto
message SubBatch {
  // ...existing fields...
  // Time allowance for processing this sub-batch, milliseconds. The worker
  // derives its budget from this field alone; it has no sizing config of its
  // own. 0 = unlimited — which is also what a consumer predating the field
  // sends, so compatibility is automatic. Soft: past it the worker stops
  // starting new work but never interrupts a running step, so the consumer's
  // ack watchdog stays the hard limit.
  uint64 soft_budget_ms = 6;
}

enum SubBatchStatus {
  // ...existing values...
  // Some messages were processed and acked; the rest timed out and must be
  // redelivered. `SubBatchAck.timed_out` lists them.
  SUB_BATCH_STATUS_PARTIAL = 4;
}

message SubBatchAck {
  // ...existing fields...
  // Indices into SubBatch.messages the budget cut off. Set only on PARTIAL.
  repeated uint32 timed_out = 5;
}
```

The budget is a relative allowance rather than an absolute deadline, so clock skew is irrelevant; time spent on the wire and in HTTP/2 buffers stays invisible to the worker, which is why the consumer sizes it well under the watchdog (see rollout) and the watchdog remains the backstop.

Compatibility is already designed in: a consumer that predates `PARTIAL` treats it like `BUSY` — fence the worker stream in order as retriable and replay the tail — so a budget-enabled worker never corrupts an old consumer, it just wastes the partial progress.

The ack shape carries a hard invariant, validated fail-closed on the consumer: `PARTIAL` requires `timed_out` to be non-empty and `accepted + timed_out.len() == messages.len()`; `OK` requires it empty.
An ack violating any of it is a protocol error handled like `FAILED` — fence the stream and replay.
The consumer must never derive acceptance from the list without that validation: proto3 cannot distinguish an unset list from an empty one, so trusting it would turn a worker bug into silently lost messages, where fencing turns it into a replay.

## Consumer changes

This is the largest piece outside the framework.
The stash, the cascade rule, and the ordered flush are reused as-is, but everything between the ack and the stash needs real work:

- Regenerate the proto; stamp the budget on each `SubBatch` from new config (suggested: `INGESTION_WORKER_SUB_BATCH_SOFT_BUDGET_MS`, default 0 = unlimited, today's semantics; when set, ≈ 0.5 × `INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS`). This is the system's only budget-sizing knob.
- **A per-message reply shape.** The transport reply today is all-or-nothing (`Accepted { accepted, messages }`), and a sub-batch the transport split into size-bounded chunks acks per chunk — the transport must remap each chunk's `timed_out` indices back to sub-batch positions and merge the chunk dispositions into one resolution.
- **A mixed resolve path.** Today a sub-batch resolves fully (release keys, advance counts) or fails fully (`defer_failed` stashes everything). Partial acceptance needs a resolve that releases completed messages and stashes the rest while preserving the dispatcher's outstanding-count invariants (the count nets to unchanged for stashed keys and never dips to zero mid-handoff).
- **Per-key acked watermarks computed from completed messages only.** The order sentinel advances a key's watermark using the key's maximum offset in the sub-batch; on a partial ack that would advance past unprocessed offsets and flag the redelivery as a resend-after-ack violation. The watermark must come from the completed subset.
- **An escalation ladder for events that never fit the budget.** Such an event would otherwise redeliver forever — the deferral path has no attempt cap — with each round ending in the flush-stall bail and a process restart, the watchdog fully masked. Stash entries produced by partial acks carry an attempt count; after N budget-limited attempts the message resends with budget 0 (unlimited), degrading to exactly today's semantics (full watchdog window, fence on overrun) for that message alone, with a counter so the pathological event is visible instead of masked.
  Every `timed_out` occurrence increments the count, admission-queue expiries included — acceptable, because an escalated event just resends unbudgeted once and processes normally.
- Offset commit accounting is unchanged in kind: partially accepted sub-batches hold commits exactly the way deferred groups do today, just for fewer messages.

## What this deliberately does not do

- **No forced preemption, and no worker-side hard deadline.**
  JavaScript cannot cancel a running `await`, and the framework never races one: the budget stops work from starting; work already started finishes.
  Worst case is soft + in-flight step tail + afterBatch flush + settled barrier.
  A genuinely hung await falls to the ack watchdog, as today (§ alternatives considered for the dropped middle rung).
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
- Timeout results by last step (the existing `ingestion_pipeline_result` counter gains the timeout label value) — timeouts indict slow steps.
- Overrun histogram — time from budget expiry to batch completion; this is the tail the checkpoints cannot cut, and the input for choosing which steps need a time policy of their own.
- Consumer side — partial acks, messages redelivered after partial, budget-exempt escalations.

There is no shadow mode: enforcement follows the wire, and the rollout ramp is consumer-side sizing — a generous budget enforces rarely, and each rare timeout exercises the real partial-ack path at negligible volume.

## Rollout

1. **Framework** — `TIMEOUT`, `BatchBudget`, the per-feed budget argument, the two checkpoints, metrics, a framework docs chapter, and stall-investigation cases for the count invariant and within-batch prefix property under budgets.
   The budget argument defaults to unlimited: zero behavior change, and no optional-budget code path ever exists.
2. **Consumer per-key serialization** — before enforcement, the consumer must never keep two sub-batches with the same routing key in flight (§ the ordering hazard): a dispatcher hold on keys with unacked messages, or the driver model's one-release rule.
   Budgets stay unsent (`soft_budget_ms = 0`) until this holds.
3. **Wire + worker** — proto fields, `PARTIAL` acks in `WorkerIngestServer`, dispositions in `GrpcStreamIngestDriver`, and the budget built at the driver's feed call; the worker has no budget knob at all — enforcement follows the wire.
   Inert in production until a consumer sends a budget.
4. **Consumer** — proto regen, budget stamping, the per-message reply shape with chunk index remapping, the mixed resolve path, completed-only watermarks, the escalation ladder, and e2e coverage in `grpc_transport_test.rs` and the integration harness.
   Enable end to end, budget ≈ 0.5 × watchdog.
5. **Per-step time policy** — for the steps the overrun metrics indict (person merge internals, hog transformer fetches), design separate step-level configuration that derives per-call client deadlines from the batch budget without changing step signatures.

## Implementation plan (commit by commit)

The rollout stages above are deployment stages; this section is the review story — the sequence of commits, each one concern, each leaving the tree green (typecheck plus the touched area's tests) and the pipeline's behavior unchanged until a consumer sends a budget.
Commit subjects are fixed; a commit that cannot be built as specified is a finding to report, not a license to restructure silently.

### Phase A — framework core (commits 1–7)

Everything here is inert: no code constructs a limited budget until Phase C builds one from the wire field.

1. `feat(ingestion): add a timeout pipeline result`
   `results.ts` gains the `TIMEOUT` member, its result type (reason-carrying, like `DROP`), the `timeout()` constructor, and the `isTimeoutResult` guard.
   Every exhaustive switch over the union updates in the same commit with the no-op semantics: result handling neither produces nor DLQs, and a fan-out parent times out when a sub-result does.
   Reviewable alone as: the union grows one "handled elsewhere, redeliver" member that nothing yet emits.
2. `feat(ingestion): add BatchBudget with a soft deadline`
   New `batch-budget.ts` exactly per the framework interface section: `softDeadline()`, the `unlimited()` singleton, `softAt`, `exhausted` (flipped once by an internal unref'd timer — no clock call on the hot path), `settle()`.
   Unit tests with fake timers.
   No consumers yet.
3. `feat(ingestion): feed a budget with each batch`
   `feed()` gains a third argument defaulting to the unlimited budget; `feedSerialized` stamps it into each element's context next to `messageId`; `fanOut` / `filterMap` sub-contexts copy it like `debugContext`.
   Zero behavior change; tests assert the stamp, the copy, and the default.
4. `feat(ingestion): soft-budget checkpoint in StepPipeline`
   `StepPipeline.process` checks the element's budget (from its context) before invoking a step on an OK result: exhausted → `timeout('budget exceeded before <step>')`.
   The step itself is invoked with one argument and sees nothing.
   Tests: mid-chain expiry short-circuits all later steps.
5. `feat(ingestion): soft-budget checkpoint for chunk steps`
   `applyChunkStepToResults` partitions per element — exhausted OK elements become timeout and pass through, the step runs on the remainder — because one chunk can mix elements from batches with different budgets.
   Tests cover the mixed-budget chunk.
6. `feat(ingestion): budget observability`
   `ingestion_batch_budget_checkpoint_total`, `ingestion_batch_budget_exhausted_total`, and the overrun histogram (budget expiry → batch completion) land in `metrics.ts`, emitted from the checkpoints and from `BatchingPipeline` at batch completion, which also settles the budget's timer.
7. `chore(ingestion): framework docs chapter and invariant cases for budgets`
   A new executable docs chapter (`18-batch-budgets.test.ts`) in the house style, plus invariant cases: the N-in/N-out count invariant under budget expiry, and the within-batch per-key prefix property.

### Phase C — wire and worker (commits 8–11)

8. `feat(ingestion): sub-batch soft budget and PARTIAL status on the wire`
   The proto changes from the wire-protocol section verbatim (`soft_budget_ms = 6`, `SUB_BATCH_STATUS_PARTIAL = 4`, `timed_out = 5`), with regenerated code per `proto/README.md`.
   Nothing reads or writes the new fields yet.
9. `feat(ingestion): build the wire soft budget at feed`
   `WorkerIngestServer` stamps `armedAt` at frame read and hands the wire allowance to the driver, which builds the batch's budget at its feed call — `0 → unlimited`, else a soft deadline at `armedAt + budget` via the shared helper.
10. `feat(ingestion): time out parked sub-batches at admission`
    The admission wait races the soft deadline via the shared helper; a sub-batch that expires parked acks `PARTIAL` with every message timed out, without being fed.
11. `feat(ingestion): PARTIAL acks with per-message dispositions`
    `CompletedSubBatch` gains `accepted` / `timedOut` computed from the completed batch's elements in feed order; the server acks `PARTIAL` when `timedOut` is non-empty after `settled`, `OK` otherwise.
    Tests assert the ack invariant from the wire-protocol section.

### Phase D — consumer (follow-up PR, commits 12–18)

This branch stays on the Node.js side; the consumer commits land in a follow-up PR.
The wire compatibility rules make the split safe: an old consumer treats `PARTIAL` as retriable `BUSY`, and no consumer sends a budget yet, so the worker's budgets are all unlimited and no `PARTIAL` ack is ever produced.

12. `feat(ingestion-consumer): stamp the sub-batch soft budget from config`
    `INGESTION_WORKER_SUB_BATCH_SOFT_BUDGET_MS` (default 0 — today's semantics), stamped on every `SubBatch`.
13. `feat(ingestion-consumer): parse PARTIAL acks fail-closed`
    The ack invariant validates on receipt — `timed_out` non-empty, `accepted + timed_out.len() == messages.len()`, `OK` requires it empty; violations handle like `FAILED`.
    A valid `PARTIAL` temporarily takes the existing retriable path (what an old consumer does), so this commit is safe before the mixed resolve exists.
14. `feat(ingestion-consumer): remap chunk dispositions to sub-batch indices`
    The transport's per-message reply shape replaces all-or-nothing acceptance: each 413-split chunk's `timed_out` indices remap to sub-batch positions and merge into one resolution.
15. `feat(ingestion-consumer): mixed resolve — release completed, stash the remainder`
    The dispatcher resolves a partial ack by releasing completed messages and stashing the rest, preserving the outstanding-count invariants (net unchanged for stashed keys, never zero mid-handoff); the cascade rule then defers newer groups behind the stash as today.
16. `feat(ingestion-consumer): advance watermarks from completed messages only`
    The order sentinel computes a key's watermark from the completed subset of a partial ack, so redelivery of the remainder is not a resend-after-ack violation.
17. `feat(ingestion-consumer): escalate never-fitting events to unbudgeted resends`
    Stash entries from partial acks carry an attempt count; every `timed_out` occurrence increments it; after N budget-limited attempts the message resends with budget 0, with a counter.
18. `chore(ingestion-consumer): e2e coverage for partial acks`
    `grpc_transport_test.rs` and the integration harness: partial ack → redelivery → completion, hot-key ordering preserved across partial acks, the escalation path.

Out of scope for this branch: the consumer (Phase D, a follow-up PR), a per-step time policy (rollout stage 5 — driven by production overrun metrics), a worker-side hard deadline (designed, implemented, and dropped — § alternatives considered), and any production config enabling budgets.

## Alternatives considered

- **Hard abort via `Promise.race` per step** — rejected.
  The losing promise keeps running with batch-bound store views; its late completion corrupts `BatchingPipeline` bookkeeping (unknown `messageId` → poisoned pipeline → server suicide) and recreates concurrent double-processing inside one process.
- **A worker-side hard deadline** — a second deadline at which the framework stops _waiting_: settle the batch where it stands, track stranded continuations in a zombie registry that swallows their late results, cap the zombies for backpressure.
  Designed, implemented, and dropped: production step timings show single-step overruns are vanishingly rare and uncorrelated with lag — lag is many cheap events, not one slow one — so the soft deadline recovers the batch and the watchdog already fences the rare wedged step.
  The zombie bookkeeping and its store-write semantics were real complexity buying a third ladder rung the system does not need.
- **A worker-side shadow/enforce flag** — a rollout gate that would record what enforcement would have done without changing results.
  Dropped: shadow could never exercise the `PARTIAL` path it was meant to de-risk, while a generously sized budget enforces rarely and tests the real path at negligible volume — so the consumer's sizing is the better ramp, and the worker keeps zero budget configuration.
- **A separate `rejected` disposition for elements refused without being attempted** — carried while the order gate existed, dropped with it.
  The consumer treats every unacked message the same way (redeliver), and the escalation ladder counts every `timed_out` — admission-queue expiries included, which is benign.
  A refusal disposition can return as a new ack field when something real produces it.
- **Respond partial and let the whole batch keep running in the background** — rejected: the admission slot leaks and the original problem returns in-process wholesale.
  The soft deadline instead stops dispatch and lets the batch drain, so the slot is released when the in-flight tail finishes.
- **Rely on the watchdog fence alone (status quo)** — rejected: fencing replays the whole un-acked tail while the worker keeps working, which is the duplication and contention this proposal removes.
- **Absolute deadlines on the wire instead of `budget_ms`** — rejected: clock skew between consumer and worker turns into silent budget errors; a relative allowance armed at frame read is skew-free, and the watchdog already covers wire-time blindness.
- **Cancel only at sub-batch boundaries (no mid-batch checkpoints)** — rejected: a single slow event would still pin the whole sub-batch until it finishes, which under a 60 s watchdog is precisely the current failure mode.
