/**
 * # Chapter 17: Accumulating Pipelines
 *
 * ## Why this exists
 *
 * Some sinks want few, large writes. Session replay folds thousands of Kafka
 * messages into one batch recorder and writes it to S3 once the batch is big
 * or old enough. That batch boundary spans many Kafka polls, so no earlier
 * shape fits: a batching pipeline's batch (chapter 14) is exactly one feed()
 * call. `newAccumulatingPipeline` owns the boundary instead: it keeps an
 * external accumulator (the batch context), folds every fed element into it
 * through your record pipeline, and pushes the accumulator through your flush
 * pipeline when a size or age trigger fires.
 *
 * ## How to use it
 *
 * Give `newAccumulatingPipeline(config)` five things:
 *
 * - **`beforeBatch`** — mints a fresh accumulator (e.g. a session batch
 *   recorder) at the start of each cycle: before the first feed, and again
 *   after every flush. The pipeline tags the accumulator onto every element
 *   it feeds through, so record steps fold into it without shared lookups.
 * - **`pipeline`** — a plain batch pipeline of steps (chapters 2–13) that
 *   folds each element into the accumulator. It knows nothing about batches
 *   or flushes.
 * - **`afterRecord`** — the per-message bookkeeping point. It sees every
 *   drained result — OK and non-OK alike — exactly once (session replay
 *   tracks Kafka offsets here, so dropped and DLQ'd messages advance them
 *   too) and trims each element to the lightweight shape that accumulates
 *   for the flush. It must not change the element count.
 * - **`flush`** — the pipeline that persists the accumulator. It receives ONE
 *   element per flush: the batch context plus every accumulated record
 *   result, in drain order.
 * - **`shouldFlush` / `maxBatchAgeMs`** — the size and age triggers.
 *
 * Then drive it the way a Kafka consumer does: feed() every poll, loop next()
 * until null. next() returns a discriminated turn — `flushed: false` carries
 * record results, `flushed: true` carries the flush output. Make each turn's
 * side effects (e.g. DLQ produces) durable, and commit offsets only after a
 * flushed turn. Call flush() on partition revoke and stop() on shutdown, so
 * the last partial batch is never lost.
 *
 * ## The fine print
 *
 * - Side effects are lifted off each element's context into its turn — they
 *   surface exactly once, and the pipeline never schedules them; the caller
 *   makes them durable. Offsets stay outside too: afterRecord tracks them and
 *   the caller commits after a flushed turn — the pipeline never commits.
 * - The age timer only marks a flush due; a later next() call executes it, so
 *   something must keep calling next() while idle (for Kafka consumers,
 *   `callEachBatchWhenEmpty: true`). See the LIVENESS INVARIANT note in
 *   `accumulating-pipeline.ts`.
 */
import {
    AccumulatedFlushInput,
    AccumulatingResult,
    AccumulationContext,
    AfterRecordHook,
} from '~/ingestion/framework/accumulating-pipeline'
import { OkResultWithContext } from '~/ingestion/framework/batch-pipeline.interface'
import { newAccumulatingPipeline, newBatchPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isOkResult, ok } from '~/ingestion/framework/results'

interface Event {
    id: number
}

// The batch context is the accumulator, like session replay's batch recorder.
type Batch = { records: number[] }

type NoCtx = Record<string, never>

/**
 * The record pipeline is a plain batch pipeline: its fold step reads the accumulator straight off
 * each element — the accumulating pipeline tagged it on — and folds into it. `recordSideEffect`,
 * when set, is attached to each result so tests can show the accumulating pipeline lifting element
 * side effects into the turn.
 */
function buildRecordPipeline(recordSideEffect?: () => Promise<unknown>) {
    return newBatchPipelineBuilder<Event & Batch & AccumulationContext, NoCtx>()
        .sequentially((b) =>
            b.pipe(function foldIntoAccumulator(input) {
                input.records.push(input.id)
                return Promise.resolve(ok({ id: input.id }, recordSideEffect ? [recordSideEffect()] : []))
            })
        )
        .build()
}

function buildPipeline(options: {
    flushAt: number
    maxBatchAgeMs?: number
    recordSideEffect?: () => Promise<unknown>
    afterRecord?: AfterRecordHook<Event, NoCtx, Event, NoCtx>
}) {
    return newAccumulatingPipeline<Event, Event, NoCtx, NoCtx, Batch, number[], NoCtx>({
        // Mints the accumulator for each cycle — runs before the first feed and after every flush.
        beforeBatch: (builder) =>
            builder.pipe(function mintAccumulator(input) {
                const batchContext: Batch & AccumulationContext = { records: [], batchId: input.batchId }
                return Promise.resolve(ok({ batchContext }))
            }),
        pipeline: buildRecordPipeline(options.recordSideEffect),
        afterRecord: options.afterRecord ?? ((elements) => elements),
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

// Narrows a turn to its flushed variant (so the elements read as flush output) and unwraps the values.
function flushedValues(result: AccumulatingResult<Event, NoCtx, number[], NoCtx> | null): (number[] | null)[] {
    if (result === null || !result.flushed) {
        throw new Error('expected a flushed turn')
    }
    return result.elements.map((e) => (isOkResult(e.result) ? e.result.value : null))
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

        expect(flushedValues(await pipeline.next())).toEqual([[1, 2, 3]])

        // The next cycle accumulates independently of the flushed one.
        await pipeline.feed(feedEvents([4, 5, 6]))
        await pipeline.next()
        expect(flushedValues(await pipeline.next())).toEqual([[4, 5, 6]])
    })

    /**
     * afterRecord is the per-message bookkeeping point: it observes every
     * drained result exactly once, across all the feeds of a cycle — this is
     * where session replay tracks Kafka offsets and trims each result to a
     * lightweight row.
     */
    it('afterRecord sees every drained result once and its output is what accumulates', async () => {
        const observed: number[] = []
        const pipeline = buildPipeline({
            flushAt: 10,
            afterRecord: (elements) =>
                elements.map((element) => {
                    if (isOkResult(element.result)) {
                        observed.push(element.result.value.id)
                        return { ...element, result: ok({ id: element.result.value.id * 10 }) }
                    }
                    return element
                }),
        })

        await pipeline.feed(feedEvents([1, 2]))
        const turn = await pipeline.next()

        expect(observed).toEqual([1, 2])
        // The record turn (and the flush buffer) carry the hook's trimmed output.
        expect(
            turn && !turn.flushed ? turn.elements.map((e) => (isOkResult(e.result) ? e.result.value.id : null)) : null
        ).toEqual([10, 20])
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
            expect(flushedValues(await pipeline.next())).toEqual([[7]])

            await pipeline.stop()
        } finally {
            jest.useRealTimers()
        }
    })

    /**
     * The consumer contract: every turn surfaces that turn's side effects —
     * lifted off the elements' contexts — for the caller to make durable, and
     * the pipeline never commits offsets. The canonical drain loop settles
     * side effects each turn and commits only after a `flushed: true` turn —
     * so a message's produce is always durable before the offset that covers
     * it is committed.
     */
    it('surfaces side effects each turn; the caller commits only after a flushed turn', async () => {
        const log: string[] = []
        const pipeline = buildPipeline({
            flushAt: 1,
            recordSideEffect: () => {
                log.push('side-effect-settled')
                return Promise.resolve()
            },
        })

        await pipeline.feed(feedEvents([1]))

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
        expect(flushedValues(await pipeline.flush())).toEqual([[8, 9]])

        await pipeline.feed(feedEvents([10]))
        expect(flushedValues(await pipeline.stop())).toEqual([[10]])
    })
})
