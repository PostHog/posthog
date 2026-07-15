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
 * it keeps an external accumulator (the cycle context), folds every fed
 * element into it through your record pipeline, and pushes the accumulator
 * through your flush pipeline when a size or age trigger fires.
 *
 * ## How to use it
 *
 * Give `newAccumulatingPipeline(config)` five things:
 *
 * - **`beforeCycle`** — mints a fresh accumulator (e.g. a session batch
 *   recorder) at the start of each cycle: before the first feed, and again
 *   after every flush. The pipeline tags the accumulator onto every element
 *   it feeds through, so record steps fold into it without shared lookups.
 * - **`pipeline`** — a plain chunk pipeline of steps (chapters 2–13) that
 *   folds each element into the accumulator. It knows nothing about cycles
 *   or flushes.
 * - **`initialState` / `reduce`** — the explicit cycle state. The reducer
 *   runs on every result the pipeline emits, one element at a time — OK and
 *   non-OK alike, with the context still attached — so this is the
 *   per-message bookkeeping point: session replay folds each message's
 *   partition and offset into the state (drops and DLQs too, so the flush's
 *   commit advances past them). Extract what the flush needs and let the
 *   element go; nothing is retained after the reduce.
 * - **`flush`** — the pipeline that persists the cycle. It receives ONE
 *   element per flush: the cycle context plus the reduced cycle state.
 * - **`shouldFlush` / `maxCycleAgeMs`** — the size and age triggers.
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
 *   either — that belongs in a flush step, read off the reduced state.
 * - The age timer only marks a flush due; a later next() call executes it, so
 *   something must keep calling next() while idle (for Kafka consumers,
 *   `callEachBatchWhenEmpty: true`). See the LIVENESS INVARIANT note in
 *   `accumulating-pipeline.ts`.
 */
import {
    AccumulatingResult,
    BeforeCycleInput,
    CycleContext,
    CycleFlushInput,
} from '~/ingestion/framework/accumulating-pipeline'
import { newAccumulatingPipeline, newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { OkResultWithContext } from '~/ingestion/framework/chunk-pipeline.interface'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isOkResult, ok } from '~/ingestion/framework/results'

interface Event {
    id: number
}

// The cycle context is the accumulator, like session replay's batch recorder.
type Batch = { records: number[] }

// The cycle state the reducer folds every drained result into — here the ids that came out, like
// session replay's per-partition offsets.
type State = { seen: number[] }

type NoCtx = Record<string, never>

/**
 * The record pipeline is a plain chunk pipeline: its fold step reads the accumulator straight off
 * each element — the accumulating pipeline tagged it on — and folds into it. `recordSideEffect`,
 * when set, is attached to each result so tests can show the accumulating pipeline lifting element
 * side effects into the turn.
 */
function buildRecordPipeline(recordSideEffect?: () => Promise<unknown>) {
    return newChunkPipelineBuilder<Event & Batch & CycleContext, NoCtx>()
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
    maxCycleAgeMs?: number
    recordSideEffect?: () => Promise<unknown>
}) {
    return newAccumulatingPipeline<Event, Event, NoCtx, NoCtx, Batch, State, number[], NoCtx>({
        // Mints the accumulator for each cycle — runs before the first feed and after every flush.
        beforeCycle: (builder) =>
            builder.pipe(function mintAccumulator(input: BeforeCycleInput) {
                const cycleContext: Batch & CycleContext = { records: [], cycleId: input.cycleId }
                return Promise.resolve(ok({ cycleContext }))
            }),
        pipeline: buildRecordPipeline(options.recordSideEffect),
        // The reducer sees every drained result exactly once; here it collects the ids.
        initialState: () => ({ seen: [] }),
        reduce: (state, element) => {
            if (isOkResult(element.result)) {
                state.seen.push(element.result.value.id)
            }
            return state
        },
        // The flush pipeline receives ONE element: the cycle context plus the reduced state. Here
        // it "persists" by emitting the state's ids; session replay writes the recorder to S3 and
        // commits the offsets read off the state.
        flush: (builder) =>
            builder.sequentially((b) =>
                b.pipe(function writeRecords(input: CycleFlushInput<State, Batch>) {
                    return Promise.resolve(ok(input.state.seen))
                })
            ),
        shouldFlush: (cycleContext) => cycleContext.records.length >= options.flushAt,
        maxCycleAgeMs: options.maxCycleAgeMs ?? 60_000,
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
     * The accumulation cycle spans feeds: two feeds fold into the same cycle
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
     * reduced state, which the reducer folded one element at a time across
     * both feeds of the cycle. The flush also re-mints the accumulator and
     * the state, so the following cycle starts empty.
     */
    it('flushes on the size trigger and starts the next cycle with fresh state', async () => {
        const pipeline = buildPipeline({ flushAt: 3 })

        await pipeline.feed(feedEvents([1, 2, 3]))
        expect(await pipeline.next()).toMatchObject({ flushed: false })

        expect(flushedValues(await pipeline.next())).toEqual([[1, 2, 3]])

        // The next cycle reduces independently of the flushed one.
        await pipeline.feed(feedEvents([4, 5, 6]))
        await pipeline.next()
        expect(flushedValues(await pipeline.next())).toEqual([[4, 5, 6]])
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
            const pipeline = buildPipeline({ flushAt: 100, maxCycleAgeMs: 1_000 })
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

        await pipeline.feed(feedEvents([1]))

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

        await pipeline.feed(feedEvents([8, 9]))
        // No next() calls yet: flush() drains the record phase itself, then flushes.
        expect(flushedValues(await pipeline.flush())).toEqual([[8, 9]])

        await pipeline.feed(feedEvents([10]))
        expect(flushedValues(await pipeline.stop())).toEqual([[10]])
    })
})
