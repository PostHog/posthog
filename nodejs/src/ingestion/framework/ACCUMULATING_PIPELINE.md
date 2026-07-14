# AccumulatingPipeline — design doc

Status: proposed. Drives the decomposition of the session-replay flush path; the
abstraction itself is generic and session-agnostic.

## Problem

Session replay folds many Kafka poll-batches of events into per-session in-memory
recorders, then flushes on a size/age trigger. Today that lifecycle lives in two
god objects — `SessionBatchManager` and `SessionBatchRecorder` — and the flush is
one ~120-line method (`sessions/session-batch-recorder.ts` `flush()`) that
interleaves: `recorder.end()`, a **Redis** retention lookup buried inside the S3
writer (`sessions/retention-aware-batch-writer.ts` `writeSession()`), encryption,
S3 writes, console-log / feature / metadata stores, and `offsetManager.commit()`.

Because the Redis retention lookup sits on the S3-flush timeout path, Redis
slowness is misattributed to S3 (PR #66226 is patching that symptom inside the god
class — adding a `RetentionLookupError` + in-flush try/catch + a retention-service
fallback). We want the flush to be a **pipeline of steps** so each concern
(retention, encrypt, write, persist) is isolated, independently instrumented, and
uses the framework's result handling (`ok` / `drop` / `dlq` / retry). A deleted
team becomes a `drop()` in a step, not a buried exception.

The vehicle is a new framework primitive: `AccumulatingPipeline`.

## Where it sits

New framework class: `nodejs/src/ingestion/framework/accumulating-pipeline.ts`,
alongside `batching-pipeline.ts`. It implements the accumulate → fold → flush
lifecycle generically and knows nothing about sessions, S3, Redis, or Kafka
offsets.

It is a sibling of `BatchingPipeline`, not a reuse of `BufferingBatchPipeline`
(that one is a passthrough re-emit buffer used by `filterMap`). The one structural
difference from `BatchingPipeline`: the batch boundary is a `shouldFlush`
predicate (size) plus an age timer that span **many `feed()` calls**, instead of
each `feed()` being one batch.

## Locked-in decisions

1. **External accumulator.** The accumulated state (today's `SessionBatchRecorder`)
   stays a separate collaborator. The pipeline holds only a handle: `beforeBatch`
   constructs it, `drainAccumulator` snapshots + clears it, the record steps fold
   into it via batch context.
2. **Offsets entirely outside.** The pipeline emits results; the consumer does all
   offset tracking and committing. `KafkaOffsetManager` survives but is owned and
   driven by the consumer around the pipeline, never inside it.
3. **Discriminated result.** `next()` yields a `{ flushed: boolean; elements }`
   result so the consumer can tell a "messages accumulated" turn (track offsets)
   from a "batch flushed" turn (commit offsets).
4. **`beforeBatch` re-mints the accumulator** after every flush (mirrors
   `BatchingPipeline.beforePipeline`). This replaces the inline
   `new SessionBatchRecorder(...)` in `SessionBatchManager.flush()`.
5. **Timer = due-flag (option 2).** An age timer sets `flushDue = true` and calls
   `signal.resolve()`; the flush itself executes inside `next()`. The timer never
   mutates the accumulator.
6. **Final flush on `stop()`.** Graceful shutdown drains the accumulator through
   the flush pipeline so the last partial batch is persisted (stronger than
   today's discard-on-revoke), and the consumer commits those offsets before
   disconnecting.

## Core types

```ts
// Discriminated result. The consumer reads `flushed` to decide what to do with offsets.
export type AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R extends string = never> =
  // record sub-pipeline drained; elements carry {partition, offset, outcome} → consumer TRACKS offsets
  | { flushed: false; elements: BatchPipelineResultWithContext<TRecordOut, CRecordOut, R> }
  // a flush completed; elements carry which sessions/partitions persisted → consumer COMMITS offsets
  | { flushed: true;  elements: BatchPipelineResultWithContext<TFlushOut, CFlushOut, R> }

// beforeBatch hook — mirrors BatchingPipeline.beforePipeline. Mints the accumulator for the
// next cycle. Runs once before the first feed, and again after every flush.
export type BeforeAccumulationStep<CBatch> = () => Promise<CBatch & { batchId: number }>

// Reads the current cycle's accumulator and produces one flush unit per accumulated entry,
// then clears it. External collaborator — the pipeline never touches session state directly.
export type DrainAccumulator<TFlushIn, CFlushIn, CBatch> =
  (batchContext: CBatch) => OkResultWithContext<TFlushIn, CFlushIn>[]
```

## Class shape & semantics

```ts
export class AccumulatingPipeline</* … */> {
  private currentBatch: (CBatch & { batchId: number }) | null = null
  private flushDue = false
  private timer?: ReturnType<typeof setInterval>

  // Single mutex serializes ALL accumulator mutation: feed-drain, size-flush, and the
  // timer-driven flush can never run concurrently, so the external accumulator stays
  // single-threaded and the session code carries no locking burden. Mirrors BatchingPipeline.
  private pumpLimit = pLimit(1)

  // Wakes a consumer that PARKS on next() instead of polling. With callEachBatchWhenEmpty
  // the consumer never parks, so the signal is unused today; it is the liveness mechanism
  // for a future wake-driven drain loop (see "Liveness invariant" below).
  private signal = new ResettableSignal()

  constructor(
    private recordPipeline: BatchPipeline</* per-message; folds into accumulator */>,
    private beforeBatch: BeforeAccumulationStep<CBatch>,
    private drainAccumulator: DrainAccumulator</* … */>,
    private flushPipeline: BatchPipeline</* flush units → flush results */>,
    private options: {
      shouldFlush: (batchContext: CBatch) => boolean, // size predicate
      maxBatchAgeMs: number,                           // age timer interval
    },
  ) {}

  start(): void {
    this.timer = setInterval(() => {
      this.flushDue = true
      this.signal.resolve()
    }, this.options.maxBatchAgeMs)
  }

  async stop(): Promise<AccumulatingResult | null> {
    if (this.timer) clearInterval(this.timer)
    // Final flush: drain whatever is accumulated so the last partial batch is not lost.
    return this.flushNow()
  }

  feed(elements: OkResultWithContext<TRecordIn, CRecordIn>[]): void {
    // Lazily mint the first accumulator; tag elements with batchContext so the record
    // steps fold into the right manager, then push downstream.
    this.recordPipeline.feed(tagWithBatch(elements, this.ensureBatch()))
  }

  async next(): Promise<AccumulatingResult | null> {
    return this.pumpLimit(async () => {
      // 1. Drain the main (record) pipeline first; yield once it has no more elements.
      const recorded = await drainFully(this.recordPipeline)
      if (recorded.length > 0) {
        return { flushed: false, elements: recorded } // consumer tracks these offsets
      }

      // 2. Main pipeline empty → flush on size OR age.
      const sizeFlush = this.currentBatch ? this.options.shouldFlush(this.currentBatch) : false
      if (sizeFlush || this.flushDue) {
        const result = await this.flushNow()
        this.flushDue = false
        this.rearmTimer() // measure age from this flush, matching today's lastFlushTime reset
        return result
      }

      // 3. Nothing to record, nothing to flush.
      return null
    })
  }

  // Snapshot + clear the accumulator, run it through the flush pipeline, re-mint the
  // accumulator. Called from next() and stop(); always under pumpLimit.
  private async flushNow(): Promise<AccumulatingResult | null> {
    if (!this.currentBatch || isEmpty(this.currentBatch)) return null
    const units = this.drainAccumulator(this.currentBatch)
    this.flushPipeline.feed(units)
    const elements = await drainFully(this.flushPipeline)
    this.currentBatch = await this.beforeBatch()
    return { flushed: true, elements } // consumer commits these offsets
  }
}
```

Contract:

- `next()` yields once the main pipeline is drained. Record results come out as
  `flushed: false`; the flush, when due, comes out as a separate `flushed: true`
  yield. The consumer loops `next()` until `null`, branching on `flushed`.
- `next()` returns `null` when there is nothing to record and no flush is due.
- The timer only marks a flush *due*; execution rides on a `next()` call.

## Liveness invariant (MUST be an explicit code comment)

Place this verbatim above the timer setup in `accumulating-pipeline.ts` and above
the consumer's drain loop:

```ts
// LIVENESS INVARIANT — age-based flush requires next() to be called while idle.
//
// The age timer only sets flushDue; the flush executes inside next(). Something
// must therefore keep calling next() even when the topic produces no messages.
// Today that is the Kafka consumer's `callEachBatchWhenEmpty: true`: consume()
// returns [] every batchTimeoutMs (~500ms), the empty batch still reaches
// handleEachBatch([]), and the resulting next() call observes flushDue and flushes.
//
// If `callEachBatchWhenEmpty` is ever turned off, age-based flush MUST instead be
// driven by the timer's signal.resolve() waking a blocking drain loop that runs
// next() to completion. Otherwise an idle accumulator with a buffered batch and no
// next() caller would stall forever.
```

Why an empty topic does not stall a buffered batch today: `consume()` blocks for at
most `batchTimeoutMs` (default 500ms, `common/kafka/consumer/consumer-v1.ts`) and
returns `[]` when the topic is empty; with `callEachBatchWhenEmpty: true` that
empty result still reaches `handleEachBatch([])`. So `next()` is called every
~500ms regardless of traffic, and a buffered batch flushes within
~`maxBatchAgeMs + batchTimeoutMs` of the last message.

## Flush-as-steps (the payoff, session-replay side)

`flushPipeline` is built per-session with the existing builder, e.g.
`groupBy(session).concurrently(...)`:

1. `endSessionStep` — `recorder.end()` → buffer + stats
2. **`resolveRetentionStep`** — the Redis lookup, isolated, own timeout + own
   metrics. Deleted / unknown team → `drop()`. This deletes the PR's
   `RetentionLookupError` + in-flush try/catch entirely.
3. `encryptStep` — encrypt buffer with the session key
4. `writeSessionStep` — retention-routed S3 write, own S3 timeout
5. batch-finalize steps — `finishWriters`, `storeConsoleLogs`, `storeFeatures`,
   `storeMetadata`

Redis slowness now surfaces in step 2, S3 slowness in step 4 — no conflation.
`resolveRetentionStep` is the template for later lifting `SessionTracker` /
`SessionFilter` / `KeyStore` out of the record phase, after which
`SessionBatchRecorder` shrinks to just the accumulator.

## Offsets — entirely outside

All offset work moves to the consumer:

- **Track**: on a `{ flushed: false }` yield, read each element's
  `{ partition, offset, outcome }` and update the offset map. Replaces the
  `offsetManager.trackOffset()` calls inside `record()`.
- **Commit**: on a `{ flushed: true }` yield, commit offsets for the sessions /
  partitions the flush reports as persisted-or-intentionally-dropped. Replaces
  `offsetManager.commit()` inside flush.
- **Discard** on revoke: the consumer holds the manager reference and calls
  `discardPartition` directly — also outside the pipeline.

Commit granularity (all-or-nothing vs per-partition) is purely a consumer concern,
decided later without touching the abstraction.

## Mapping old → new

| Today | New |
|---|---|
| `SessionBatchManager.getCurrentBatch()` + `new SessionBatchRecorder()` on flush | `beforeBatch` hook mints the manager |
| `record()` folds events + tracks offsets | record-phase steps fold; offset tracking moves to consumer |
| `shouldFlush()` size check | `options.shouldFlush` predicate |
| `shouldFlush()` age check via `lastFlushTime` | age timer → `flushDue`, re-armed on each flush |
| `flush()` monolith | `flushPipeline` of steps + `drainAccumulator` |
| `offsetManager.commit()` inside flush | consumer commits on `{ flushed: true }` |
| retention Redis inside S3 writer | `resolveRetentionStep` |
| discard-on-revoke for last batch | final flush on `stop()` |

## Phasing

1. **`AccumulatingPipeline` + tests** as a pure framework class, no session-replay
   coupling. Mirror `batching-pipeline.test.ts` style.
2. **Behavior-preserving wrap**: `flushPipeline` = one opaque step calling today's
   `SessionBatchRecorder.flush()` logic minus the commit; `drainAccumulator`
   snapshots the recorder; `beforeBatch` mints a recorder. Move offset commit to
   the consumer. Zero behavior change — proves the seam against the e2e snapshots.
3. **Split the flush** into the steps above, starting with `resolveRetentionStep`
   — this is where the incident fix lands cleanly, as a `drop()`.
4. **Record-phase extraction**: `tracker` / `filter` / `keystore` → steps;
   `SessionBatchRecorder` becomes a thin accumulator.

## Test plan

- Framework `accumulating-pipeline.test.ts`:
  - accumulate across N feeds without flush;
  - size flush fires only when `shouldFlush` true;
  - age flush: advance fake timers past `maxBatchAgeMs`, assert a `{ flushed: true }`
    yield with no new feeds (the empty-topic / idle case);
  - `next()` returns `{ flushed: false }` for record drains and a distinct
    `{ flushed: true }` after; `null` when fully drained;
  - `beforeBatch` runs exactly once per flush boundary;
  - timer re-armed on size flush (age measured from last flush, not last tick);
  - flush-step `drop()` removes a unit without failing the batch;
  - `stop()` performs a final flush of a non-empty accumulator and clears the timer.
- Consumer: offset tracking on `{ flushed: false }`, commit on `{ flushed: true }`,
  no commit when a retriable flush step throws, discard-on-revoke still works,
  final-flush offsets committed before disconnect.
- Reuse `consumer.e2e.test.ts` snapshots as the behavior-preserving guard through
  phases 2–3.

## Remaining minor questions

1. `next()` ordering when records just drained *and* a flush is due: emit the
   `{ flushed: false }` record batch first, then `{ flushed: true }` on the next
   call (keeps the discriminant clean). Confirm.
2. `beforeBatch` failure (can't mint a manager): treat as fatal (like
   `BatchingPipeline`), or retry?
3. Narrow `{ flushed: false }` elements to just
   `{ partition, offset, sessionId, outcome }` (drop the parsed-message payload
   that the inner pipeline returns and the consumer ignores)?
