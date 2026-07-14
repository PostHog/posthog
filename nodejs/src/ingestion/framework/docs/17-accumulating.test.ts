/**
 * # Chapter 17: Accumulating Pipelines
 *
 * `newAccumulatingPipeline(config)` builds an `AccumulatingPipeline`: it wraps a
 * per-message record pipeline that folds each element into an external
 * accumulator, and flushes that accumulator through a separate flush pipeline
 * on a size or age trigger. Session replay is the motivating consumer: events
 * fold into a batch recorder across many Kafka polls, and the flush writes the
 * whole batch to storage.
 *
 * ## Key concepts
 *
 * - **The batch boundary spans many `feed()` calls.** Unlike a batching
 *   pipeline (chapter 14), where each `feed()` is one batch, an accumulation
 *   cycle keeps absorbing feeds until `shouldFlush` (size) returns true or the
 *   age timer marks a flush due.
 * - **`beforeBatch` mints the batch context** (the accumulator, e.g. a session
 *   batch recorder) once per cycle: before the first feed, and again after
 *   every flush. The pipeline tags it onto every element it feeds through, so
 *   record steps fold into it without shared mutable lookups.
 * - **`next()` returns a discriminated result.** A `flushed: false` turn
 *   carries the record pipeline's results; a `flushed: true` turn carries the
 *   flush pipeline's results. `null` means fully drained and nothing due.
 * - **Side effects are surfaced, not scheduled.** Every turn carries the side
 *   effects produced that turn (e.g. DLQ produces); the caller makes them
 *   durable. Offsets stay entirely outside too: the pipeline never commits —
 *   the caller commits after a flushed turn's side effects have settled.
 * - **The age timer only marks a flush due; `next()` executes it.** Something
 *   must keep calling `next()` while idle (see the LIVENESS INVARIANT in
 *   `accumulating-pipeline.ts`) — for Kafka consumers that is
 *   `callEachBatchWhenEmpty: true`.
 *
 * ## How it works
 *
 * ```
 * feed(A) ─► record pipeline folds A into ctx ─► next(): { flushed: false, elements: A' }
 * feed(B) ─► record pipeline folds B into ctx ─► next(): { flushed: false, elements: B' }
 *                        size or age trigger ─► next(): { flushed: true,  elements: flush(ctx) }
 *                                               beforeBatch mints a fresh ctx for the next cycle
 * ```
 *
 * `flush()` drains and flushes on demand (a Kafka partition revoke), and
 * `stop()` does the same while also clearing the age timer (shutdown), so the
 * last partial batch is never lost.
 */
import { AccumulatedFlushInput, RecordPipeline } from '~/ingestion/framework/accumulating-pipeline'
import { BatchPipelineResultWithContext, OkResultWithContext } from '~/ingestion/framework/batch-pipeline.interface'
import { BatchResult, FeedResult } from '~/ingestion/framework/batching-pipeline'
import { newAccumulatingPipeline } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isOkResult, ok } from '~/ingestion/framework/results'

interface Event {
    id: number
}

// The batch context is the accumulator, like session replay's batch recorder.
type Batch = { records: number[] }

type NoCtx = Record<string, never>

/**
 * A minimal record pipeline: folds each fed element's id into the accumulator the pipeline tagged
 * onto it, then acks the element. Real deployments pass a BatchingPipeline here (its afterBatch is
 * where offsets get tracked); the accumulating pipeline only needs the feed()/next() shape.
 */
class FoldingRecordPipeline implements RecordPipeline<Event & Batch, NoCtx, Event, NoCtx> {
    private buffer: OkResultWithContext<Event & Batch, NoCtx>[] = []

    constructor(private sideEffectPerBatch?: () => Promise<unknown>) {}

    feed(elements: OkResultWithContext<Event & Batch, NoCtx>[]): Promise<FeedResult> {
        this.buffer.push(...elements)
        return Promise.resolve({ ok: true })
    }

    next(): Promise<BatchResult<BatchPipelineResultWithContext<Event, NoCtx>> | null> {
        if (this.buffer.length === 0) {
            return Promise.resolve(null)
        }
        const out = this.buffer
        this.buffer = []
        for (const element of out) {
            element.result.value.records.push(element.result.value.id)
        }
        return Promise.resolve({
            elements: out.map((element) => ({ result: ok({ id: element.result.value.id }), context: element.context })),
            sideEffects: this.sideEffectPerBatch ? [this.sideEffectPerBatch()] : [],
        })
    }
}

function buildPipeline(options: {
    flushAt: number
    maxBatchAgeMs?: number
    recordSideEffect?: () => Promise<unknown>
}) {
    return newAccumulatingPipeline<Event, Event, NoCtx, NoCtx, Batch, number[], NoCtx>({
        // Mints the accumulator for each cycle — runs before the first feed and after every flush.
        beforeBatch: (builder) =>
            builder.pipe(function mintAccumulator(input) {
                return Promise.resolve(ok({ batchContext: { records: [], batchId: input.batchId } }))
            }),
        pipeline: new FoldingRecordPipeline(options.recordSideEffect),
        // The flush pipeline receives ONE element: the batch context plus the accumulated results.
        // Here it "persists" by emitting the accumulated records; session replay writes to S3.
        flush: (builder) =>
            builder.sequentially((b) =>
                b.pipe(function writeRecords(input: AccumulatedFlushInput<Event, NoCtx, Batch>) {
                    return Promise.resolve(ok(input.batchContext.records))
                })
            ),
        shouldFlush: (batchContext) => batchContext.records.length >= options.flushAt,
        maxBatchAgeMs: options.maxBatchAgeMs ?? 60_000,
    })
}

function feedEvents(ids: number[]): OkResultWithContext<Event, NoCtx>[] {
    return ids.map((id) => createOkContext({ id }, {}))
}

describe('Accumulating Pipelines', () => {
    /**
     * The accumulation cycle spans feeds: two feeds fold into the same batch
     * context, each drains as a `flushed: false` turn, and while the size
     * threshold is not reached next() finds nothing to flush.
     */
    it('accumulates across multiple feeds without flushing under the size threshold', async () => {
        const pipeline = buildPipeline({ flushAt: 10 })

        await pipeline.feed(feedEvents([1, 2]))
        const first = await pipeline.next()
        await pipeline.feed(feedEvents([3]))
        const second = await pipeline.next()

        expect(first).toMatchObject({ flushed: false })
        expect(second).toMatchObject({ flushed: false })
        // Drained, under threshold, no age trigger → nothing to do.
        expect(await pipeline.next()).toBeNull()
    })

    /**
     * Crossing the size threshold makes the next() after the record drain a
     * `flushed: true` turn carrying the flush pipeline's output — here the
     * accumulated records. The flush also re-mints the accumulator, so the
     * following cycle starts empty and a later flush carries only its own
     * records.
     */
    it('flushes on the size trigger and starts the next cycle with a fresh accumulator', async () => {
        const pipeline = buildPipeline({ flushAt: 3 })

        await pipeline.feed(feedEvents([1, 2, 3]))
        expect(await pipeline.next()).toMatchObject({ flushed: false })

        const flushed = await pipeline.next()
        expect(flushed).toMatchObject({ flushed: true })
        expect(flushed!.elements.map((e) => (isOkResult(e.result) ? e.result.value : null))).toEqual([[1, 2, 3]])

        // The next cycle accumulates independently of the flushed one.
        await pipeline.feed(feedEvents([4, 5, 6]))
        await pipeline.next()
        const flushedAgain = await pipeline.next()
        expect(flushedAgain).toMatchObject({ flushed: true })
        expect(flushedAgain!.elements.map((e) => (isOkResult(e.result) ? e.result.value : null))).toEqual([[4, 5, 6]])
    })

    /**
     * The age timer only marks a flush due — the flush itself executes inside a
     * later next() call. This is the liveness invariant: an idle accumulator
     * flushes only because something keeps calling next() (for Kafka consumers,
     * the empty-batch tick).
     */
    it('flushes an idle accumulator on the age trigger, executed by the next caller', async () => {
        jest.useFakeTimers()
        try {
            const pipeline = buildPipeline({ flushAt: 100, maxBatchAgeMs: 1_000 })
            pipeline.start()

            await pipeline.feed(feedEvents([7]))
            expect(await pipeline.next()).toMatchObject({ flushed: false })
            // Under the size threshold and not yet old enough: nothing happens.
            expect(await pipeline.next()).toBeNull()

            jest.advanceTimersByTime(1_500)

            // The timer has only marked the flush due; this next() executes it.
            const flushed = await pipeline.next()
            expect(flushed).toMatchObject({ flushed: true })
            expect(flushed!.elements.map((e) => (isOkResult(e.result) ? e.result.value : null))).toEqual([[7]])

            await pipeline.stop()
        } finally {
            jest.useRealTimers()
        }
    })

    /**
     * The consumer contract: every turn surfaces that turn's side effects for
     * the caller to make durable, and the pipeline never commits offsets. The
     * canonical drain loop settles side effects each turn and commits only
     * after a `flushed: true` turn — so a message's produce is always durable
     * before the offset that covers it is committed.
     */
    it('surfaces side effects each turn; the caller commits only after a flushed turn', async () => {
        const log: string[] = []
        const pipeline = buildPipeline({
            flushAt: 2,
            recordSideEffect: () => {
                log.push('side-effect-settled')
                return Promise.resolve()
            },
        })

        await pipeline.feed(feedEvents([1, 2]))

        // The canonical consumer drain loop.
        let result = await pipeline.next()
        while (result !== null) {
            await Promise.allSettled(result.sideEffects)
            if (result.flushed) {
                log.push('offsets-committed')
            }
            result = await pipeline.next()
        }

        // The record turn's side effect settled before the flush turn's commit.
        expect(log).toEqual(['side-effect-settled', 'offsets-committed'])
    })

    /**
     * `flush()` drains whatever is buffered and flushes it on demand — the
     * partition-revoke pattern, where the batch must persist (and the caller
     * commit) before the partitions are given up. `stop()` does the same and
     * clears the age timer — the shutdown pattern, so the last partial batch
     * is never lost.
     */
    it('flush() and stop() drain and flush the partial batch on demand', async () => {
        const pipeline = buildPipeline({ flushAt: 100 })

        await pipeline.feed(feedEvents([8, 9]))
        // No next() calls yet: flush() drains the record phase itself, then flushes.
        const revoked = await pipeline.flush()
        expect(revoked).toMatchObject({ flushed: true })
        expect(revoked!.elements.map((e) => (isOkResult(e.result) ? e.result.value : null))).toEqual([[8, 9]])

        await pipeline.feed(feedEvents([10]))
        const final = await pipeline.stop()
        expect(final).toMatchObject({ flushed: true })
        expect(final!.elements.map((e) => (isOkResult(e.result) ? e.result.value : null))).toEqual([[10]])
    })
})
