/**
 * # Chapter 17: Accumulating Pipelines
 *
 * ## Why this exists
 *
 * Some sinks want few, large writes. Session replay folds thousands of Kafka
 * messages into one batch recorder and writes it to S3 once the batch is big
 * or old enough. That boundary — an accumulation **cycle** — spans many Kafka
 * polls, so no earlier shape fits: a batching pipeline's batch (chapter 14) is
 * exactly one feed() call. `newAccumulatingPipeline` owns the cycle instead:
 * it drives a plain per-message pipeline, folds every result the pipeline
 * emits into an explicit cycle state, and pushes that state through your
 * flush pipeline when a size or age trigger fires.
 *
 * ## How to use it
 *
 * Give `newAccumulatingPipeline(config)` these things, in cycle-lifecycle
 * order:
 *
 * - **`maxCycleAgeMs`** — the age bound on a cycle.
 * - **`onNewCycle`** — mints the cycle state (e.g. a fresh session batch
 *   recorder plus the offsets to commit), lazily for the cycle's first
 *   result and again after every flush.
 * - **`pipeline`** — a plain chunk pipeline of steps (chapters 2–13) that
 *   takes messages in and emits the data to accumulate. It never sees the
 *   cycle.
 * - **`reduce`** — a pipeline of steps that folds every result the record
 *   pipeline emits into the state, one element at a time. Each step takes a
 *   `ReduceInput` — the state paired with the drained element, whose result
 *   (OK and non-OK alike, context attached) is data by then — and the last
 *   step returns the new state. This is the per-message bookkeeping point:
 *   session replay folds every message's offset in (drops and DLQs too, so
 *   the flush's commit advances past them) and records OK results into the
 *   state's recorder. Extract what the flush needs and let the element go;
 *   nothing is retained after the reduce.
 * - **`shouldFlush`** — the size trigger that closes the cycle.
 * - **`flush`** — the pipeline that persists the cycle. It receives ONE
 *   element per flush: the cycle state.
 *
 * Then drive it the way a Kafka consumer does: feed() every poll, loop next()
 * until null. next() returns a discriminated turn — `flushed: false` means
 * record work happened (its results were reduced into the state),
 * `flushed: true` carries the flush output. Make each turn's side effects
 * durable. Call flush() on partition revoke and stop() on shutdown, so the
 * last partial cycle is never lost.
 *
 * ## The fine print
 *
 * - Side effects still on an element's context when it drains are lifted into
 *   that turn — they surface exactly once, and the pipeline never schedules
 *   them; the caller makes them durable. The pipeline never commits offsets
 *   either — that belongs in a flush step, read off the cycle state.
 * - Elements bind to a cycle when they are reduced, not when they are fed —
 *   a feed that races a flush simply lands in the next cycle.
 * - The age timer only marks a flush due; a later next() call executes it, so
 *   something must keep calling next() while idle (for Kafka consumers,
 *   `callEachBatchWhenEmpty: true`). See the LIVENESS INVARIANT note in
 *   `accumulating-pipeline.ts`.
 */
import { AccumulatingResult } from '~/ingestion/framework/accumulating-pipeline'
import { newAccumulatingPipeline, newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { OkResultWithContext } from '~/ingestion/framework/chunk-pipeline.interface'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isOkResult, ok } from '~/ingestion/framework/results'

interface Event {
    id: number
}

// The cycle state is the one accumulator, like session replay's recorder plus its offsets.
type State = { records: number[] }

type NoCtx = Record<string, never>

/**
 * The record pipeline is a plain chunk pipeline that never sees the cycle: it processes each
 * message and emits the data the reducer folds into the state. `recordSideEffect`, when set, is
 * attached to each result so tests can show the accumulating pipeline lifting element side effects
 * into the turn.
 */
function buildRecordPipeline(recordSideEffect?: () => Promise<unknown>) {
    return newChunkPipelineBuilder<Event, NoCtx>()
        .sequentially((b) =>
            b.pipe(function processEvent(input) {
                return Promise.resolve(ok({ id: input.id }, recordSideEffect ? [recordSideEffect()] : []))
            })
        )
        .build()
}

function buildPipeline(options: {
    flushAt: number
    maxCycleAgeMs?: number
    recordSideEffect?: () => Promise<unknown>
}) {
    return newAccumulatingPipeline<Event, Event, NoCtx, NoCtx, State, number[], NoCtx>({
        maxCycleAgeMs: options.maxCycleAgeMs ?? 60_000,
        // Mints the cycle's accumulator — lazily for the first result, and again after every flush.
        onNewCycle: () => ({ records: [] }),
        pipeline: buildRecordPipeline(options.recordSideEffect),
        // The reduce pipeline sees every drained result exactly once; here one step folds the ids
        // in and returns the state.
        reduce: (builder) =>
            builder.pipe(function foldIntoState(input) {
                if (isOkResult(input.element.result)) {
                    input.state.records.push(input.element.result.value.id)
                }
                return Promise.resolve(ok(input.state))
            }),
        shouldFlush: (state) => state.records.length >= options.flushAt,
        // The flush pipeline receives ONE element: the cycle state. Here it "persists" by emitting
        // the accumulated records; session replay writes the state's recorder to S3 and commits the
        // offsets read off the state.
        flush: (builder) =>
            builder.sequentially((b) =>
                b.pipe(function writeRecords(state: State) {
                    return Promise.resolve(ok(state.records))
                })
            ),
    })
}

function feedEvents(ids: number[]): OkResultWithContext<Event, NoCtx>[] {
    return ids.map((id) => createOkContext({ id }, {}))
}

// Narrows a turn to its flushed variant (so the elements read as flush output) and unwraps the values.
function flushedValues(result: AccumulatingResult<number[], NoCtx> | null): (number[] | null)[] {
    if (result === null || !result.flushed) {
        throw new Error('expected a flushed turn')
    }
    return result.elements.map((e) => (isOkResult(e.result) ? e.result.value : null))
}

describe('Accumulating Pipelines', () => {
    /**
     * The accumulation cycle spans feeds: two feeds reduce into the same cycle
     * state, each drains as a `flushed: false` turn, and while the size
     * threshold is not reached next() finds nothing to flush.
     */
    it('accumulates across multiple feeds without flushing under the size threshold', async () => {
        const pipeline = buildPipeline({ flushAt: 10 })

        pipeline.feed(feedEvents([1, 2]))
        const first = await pipeline.next()
        pipeline.feed(feedEvents([3]))
        const second = await pipeline.next()

        expect(first).toMatchObject({ flushed: false })
        expect(second).toMatchObject({ flushed: false })
        // Drained, under threshold, no age trigger → nothing to do.
        expect(await pipeline.next()).toBeNull()
    })

    /**
     * Crossing the size threshold makes the next() after the record drain a
     * `flushed: true` turn carrying the flush pipeline's output — the reduced
     * state, folded one element at a time across both feeds of the cycle. The
     * next cycle starts from a fresh state.
     */
    it('flushes on the size trigger and starts the next cycle with fresh state', async () => {
        const pipeline = buildPipeline({ flushAt: 3 })

        pipeline.feed(feedEvents([1, 2, 3]))
        expect(await pipeline.next()).toMatchObject({ flushed: false })

        expect(flushedValues(await pipeline.next())).toEqual([[1, 2, 3]])

        // The next cycle reduces independently of the flushed one.
        pipeline.feed(feedEvents([4, 5, 6]))
        await pipeline.next()
        expect(flushedValues(await pipeline.next())).toEqual([[4, 5, 6]])
    })

    /**
     * The age timer only marks a flush due — the flush itself executes inside a
     * later next() call. This is the liveness invariant: an idle cycle flushes
     * only because something keeps calling next() (for Kafka consumers, the
     * empty-batch tick).
     */
    it('flushes an idle cycle on the age trigger, executed by the next caller', async () => {
        jest.useFakeTimers()
        try {
            const pipeline = buildPipeline({ flushAt: 100, maxCycleAgeMs: 1_000 })
            pipeline.start()

            pipeline.feed(feedEvents([7]))
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
     * the pipeline itself never schedules them. The canonical drain loop
     * settles side effects each turn.
     */
    it('surfaces side effects each turn for the caller to settle', async () => {
        const log: string[] = []
        const pipeline = buildPipeline({
            flushAt: 1,
            recordSideEffect: () => {
                log.push('side-effect-settled')
                return Promise.resolve()
            },
        })

        pipeline.feed(feedEvents([1]))

        // The canonical consumer drain loop.
        let result = await pipeline.next()
        while (result !== null) {
            await Promise.allSettled(result.sideEffects)
            if (result.flushed) {
                log.push('flushed')
            }
            result = await pipeline.next()
        }

        // The record turn's side effect settled before the flush turn.
        expect(log).toEqual(['side-effect-settled', 'flushed'])
    })

    /**
     * `flush()` drains whatever is buffered and flushes it on demand — the
     * partition-revoke pattern, where the cycle must persist (and its flush
     * steps commit) before the partitions are given up. `stop()` does the same
     * and clears the age timer — the shutdown pattern, so the last partial
     * cycle is never lost.
     */
    it('flush() and stop() drain and flush the partial cycle on demand', async () => {
        const pipeline = buildPipeline({ flushAt: 100 })

        pipeline.feed(feedEvents([8, 9]))
        // No next() calls yet: flush() drains the record phase itself, then flushes.
        expect(flushedValues(await pipeline.flush())).toEqual([[8, 9]])

        pipeline.feed(feedEvents([10]))
        expect(flushedValues(await pipeline.stop())).toEqual([[10]])
    })
})
