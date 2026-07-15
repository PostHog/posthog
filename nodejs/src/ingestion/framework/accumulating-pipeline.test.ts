import { AccumulatingPipeline, AccumulatingResult, ReduceInput } from './accumulating-pipeline'
import { newPipelineBuilder } from './builders'
import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { createOkContext } from './helpers'
import { PipelineResultType, drop, isOkResult, ok } from './results'
import { ProcessingStep } from './steps'

type RecordIn = { id: number }
// The cycle state is the one accumulator, like session replay's recorder plus its offsets.
type State = { records: number[] }

// Flush pipeline: receives the cycle state (one element), captures it for assertions, and emits
// its accumulated records.
class RecordsFlushPipeline implements ChunkPipeline<State, number[], Record<string, never>, Record<string, never>> {
    public lastFlushedState: State | null = null
    private buffer: OkResultWithContext<State, Record<string, never>>[] = []

    feed(elements: OkResultWithContext<State, Record<string, never>>[]): void {
        this.buffer.push(...elements)
    }

    next(): Promise<ChunkPipelineResultWithContext<number[], Record<string, never>> | null> {
        if (this.buffer.length === 0) {
            return Promise.resolve(null)
        }
        const out = this.buffer
        this.buffer = []
        return Promise.resolve(
            out.map((element) => {
                this.lastFlushedState = element.result.value
                return {
                    result: ok(element.result.value.records),
                    context: element.context,
                }
            })
        )
    }
}

// Concatenates the records emitted by RecordsFlushPipeline out of a flushed result.
function flushedRecords(result: AccumulatingResult<number[], Record<string, never>> | null): number[] {
    if (!result || !result.flushed) {
        return []
    }
    return result.elements.flatMap((element) => (isOkResult(element.result) ? element.result.value : []))
}

function feedBatch(ids: number[]): OkResultWithContext<RecordIn, Record<string, never>>[] {
    return ids.map((id) => createOkContext({ id }, {}))
}

// Echoes each fed element back out — a plain chunk pipeline that never sees the cycle; the reducer
// does the folding. Negative ids come out as drop results (the reducer must still see them —
// bookkeeping like offset tracking covers dropped messages too). `sideEffectPerDrain`, when set, is
// attached to the first emitted element's context per drain, so tests can assert the accumulating
// pipeline lifts element side effects into the turn.
class EchoRecordPipeline implements ChunkPipeline<RecordIn, RecordIn, Record<string, never>, Record<string, never>> {
    private buffer: OkResultWithContext<RecordIn, Record<string, never>>[] = []

    constructor(private sideEffectPerDrain?: () => Promise<unknown>) {}

    feed(elements: OkResultWithContext<RecordIn, Record<string, never>>[]): void {
        this.buffer.push(...elements)
    }

    next(): Promise<ChunkPipelineResultWithContext<RecordIn, Record<string, never>> | null> {
        if (this.buffer.length === 0) {
            return Promise.resolve(null)
        }
        const out = this.buffer
        this.buffer = []
        return Promise.resolve(
            out.map((element, index) => {
                if (index === 0 && this.sideEffectPerDrain) {
                    element.context.sideEffects = [this.sideEffectPerDrain()]
                }
                const id = element.result.value.id
                return {
                    result: id >= 0 ? ok({ id }) : drop<RecordIn>('negative id'),
                    context: element.context,
                }
            })
        )
    }
}

describe('AccumulatingPipeline', () => {
    let onNewCycle: jest.Mock
    let flushPipeline: RecordsFlushPipeline
    let reducedTypes: PipelineResultType[]

    type Reduce = ReduceInput<State, RecordIn, Record<string, never>>

    function createPipeline(options: {
        flushAt: number
        maxCycleAgeMs?: number
        recordSideEffect?: () => Promise<unknown>
        reduceStep?: ProcessingStep<Reduce, State>
    }) {
        onNewCycle = jest.fn((): State => ({ records: [] }))
        flushPipeline = new RecordsFlushPipeline()
        reducedTypes = []

        const reduceStep =
            options.reduceStep ??
            function foldIdsStep(input: Reduce) {
                reducedTypes.push(input.element.result.type)
                if (isOkResult(input.element.result)) {
                    input.state.records.push(input.element.result.value.id)
                }
                return Promise.resolve(ok(input.state))
            }

        return new AccumulatingPipeline<
            RecordIn,
            RecordIn,
            Record<string, never>,
            Record<string, never>,
            State,
            number[],
            Record<string, never>
        >({
            maxCycleAgeMs: options.maxCycleAgeMs ?? 60_000,
            onNewCycle,
            pipeline: new EchoRecordPipeline(options.recordSideEffect),
            reduce: newPipelineBuilder<Reduce, Record<string, never>>().pipe(reduceStep).build(),
            shouldFlush: (state) => state.records.length >= options.flushAt,
            flushPipeline,
        })
    }

    async function drainNext(pipeline: ReturnType<typeof createPipeline>) {
        return await pipeline.next()
    }

    it('accumulates across feeds and does not flush under the size threshold', async () => {
        const pipeline = createPipeline({ flushAt: 5 })

        pipeline.feed(feedBatch([1, 2]))
        const recorded = await drainNext(pipeline)
        pipeline.feed(feedBatch([3]))
        await drainNext(pipeline)

        expect(recorded).toEqual({ flushed: false, sideEffects: [] })
        // record drained, state under threshold → next() finds nothing to flush
        expect(await drainNext(pipeline)).toBeNull()
        // the cycle state was minted exactly once (no flush → no re-mint)
        expect(onNewCycle).toHaveBeenCalledTimes(1)
    })

    it('flushes on the size trigger and re-mints the state', async () => {
        const pipeline = createPipeline({ flushAt: 3 })

        pipeline.feed(feedBatch([1, 2, 3]))
        const recorded = await drainNext(pipeline)
        expect(recorded).toMatchObject({ flushed: false })

        const flushed = await drainNext(pipeline)
        expect(flushed).toMatchObject({ flushed: true })
        expect(flushedRecords(flushed)).toEqual([1, 2, 3])

        // re-mint is lazy: the next cycle's state is minted when its first result is reduced
        pipeline.feed(feedBatch([4]))
        await drainNext(pipeline)
        expect(onNewCycle).toHaveBeenCalledTimes(2)
        await pipeline.flush()
        expect(flushPipeline.lastFlushedState).toEqual({ records: [4] })
    })

    it('emits record results first, then the flush on the next call', async () => {
        const pipeline = createPipeline({ flushAt: 2 })

        pipeline.feed(feedBatch([1, 2]))

        const first = await drainNext(pipeline)
        expect(first).toMatchObject({ flushed: false })

        const second = await drainNext(pipeline)
        expect(second).toMatchObject({ flushed: true })

        expect(await drainNext(pipeline)).toBeNull()
    })

    it('returns null when there is nothing to record and nothing to flush', async () => {
        const pipeline = createPipeline({ flushAt: 5 })
        expect(await drainNext(pipeline)).toBeNull()
        expect(onNewCycle).not.toHaveBeenCalled()
    })

    // The reduce pipeline is the per-message bookkeeping point: it must see every drained result
    // exactly once — non-OK included, since e.g. the offsets a flush commits must cover dropped
    // messages.
    it('reduces every drained result into the cycle state, non-OK included', async () => {
        const pipeline = createPipeline({ flushAt: 100 })

        pipeline.feed(feedBatch([1, -2, 3]))
        await drainNext(pipeline)

        expect(reducedTypes).toEqual([PipelineResultType.OK, PipelineResultType.DROP, PipelineResultType.OK])

        await pipeline.flush()
        expect(flushPipeline.lastFlushedState).toEqual({ records: [1, 3] })
    })

    // A drained element's fate is already sealed, so the reduce pipeline has no business dropping
    // or DLQing — a non-OK result from it means silently skipped bookkeeping (e.g. an uncommitted
    // offset), which is a broken invariant.
    it('throws when the reduce pipeline returns a non-ok result', async () => {
        const pipeline = createPipeline({
            flushAt: 100,
            reduceStep: function droppingReduceStep() {
                return Promise.resolve(drop('reduce should never drop'))
            },
        })

        pipeline.feed(feedBatch([1]))

        await expect(pipeline.next()).rejects.toThrow('reduce pipeline returned non-ok result')
    })

    it('surfaces side effects attached by reduce steps on the turn', async () => {
        const reduceProduce = Promise.resolve('reduce produce')
        const pipeline = createPipeline({
            flushAt: 100,
            reduceStep: function reduceWithSideEffect(input: Reduce) {
                return Promise.resolve(ok(input.state, [reduceProduce]))
            },
        })

        pipeline.feed(feedBatch([1]))
        const recorded = await drainNext(pipeline)

        expect(recorded?.sideEffects).toEqual([reduceProduce])
    })

    it('surfaces the record elements side effects on a record turn', async () => {
        const recordSideEffect = jest.fn().mockResolvedValue(undefined)
        const pipeline = createPipeline({ flushAt: 100, recordSideEffect })

        pipeline.feed(feedBatch([1, 2]))
        const recorded = await drainNext(pipeline)

        expect(recorded).toMatchObject({ flushed: false })
        expect(recorded?.sideEffects).toHaveLength(1)
    })

    // Elements are let go at drain time — the flush must not re-surface a side effect that already
    // surfaced on its record turn.
    it('lifts element side effects once — the flush turn does not re-surface them', async () => {
        const recordSideEffect = jest.fn().mockResolvedValue(undefined)
        const pipeline = createPipeline({ flushAt: 100, recordSideEffect })

        pipeline.feed(feedBatch([1]))
        const recorded = await drainNext(pipeline)
        expect(recorded?.sideEffects).toHaveLength(1)

        const flushed = await pipeline.stop()
        expect(flushed).toMatchObject({ flushed: true })
        expect(flushed?.sideEffects).toEqual([])
    })

    it('flush() drains buffered records and flushes immediately, below the size threshold', async () => {
        const pipeline = createPipeline({ flushAt: 100 })

        pipeline.feed(feedBatch([1, 2]))
        // No next() drain: flush() must fold the buffered records in itself before flushing.
        const flushed = await pipeline.flush()

        expect(flushed).toMatchObject({ flushed: true })
        expect(flushedRecords(flushed)).toEqual([1, 2])
        // Nothing was reduced since — there is no state, so a forced flush has nothing to do.
        expect(await pipeline.flush()).toBeNull()
    })

    describe('age timer', () => {
        beforeEach(() => jest.useFakeTimers())
        afterEach(() => jest.useRealTimers())

        it('flushes a buffered cycle once the age elapses with no further feeds (idle topic)', async () => {
            const pipeline = createPipeline({ flushAt: 100, maxCycleAgeMs: 1000 })
            pipeline.start()

            pipeline.feed(feedBatch([1]))
            await drainNext(pipeline) // drain the record ack; under size threshold, no flush yet
            expect(await drainNext(pipeline)).toBeNull()

            jest.advanceTimersByTime(1000)

            const flushed = await drainNext(pipeline)
            expect(flushed).toMatchObject({ flushed: true })
            expect(flushedRecords(flushed)).toEqual([1])

            await pipeline.stop()
        })

        it('re-arms the timer on flush so age is measured from the last flush', async () => {
            const pipeline = createPipeline({ flushAt: 1, maxCycleAgeMs: 1000 })
            pipeline.start()

            // size flush at the first element
            pipeline.feed(feedBatch([1]))
            await drainNext(pipeline)
            const sizeFlush = await drainNext(pipeline)
            expect(sizeFlush).toMatchObject({ flushed: true })

            // less than maxCycleAgeMs since that flush, no state → no age flush
            jest.advanceTimersByTime(999)
            expect(await drainNext(pipeline)).toBeNull()

            await pipeline.stop()
        })

        it('waitForActivity resolves when the timer fires', async () => {
            const pipeline = createPipeline({ flushAt: 100, maxCycleAgeMs: 1000 })
            pipeline.start()

            let woke = false
            const activity = pipeline.waitForActivity().then(() => {
                woke = true
            })

            jest.advanceTimersByTime(1000)
            await activity
            expect(woke).toBe(true)

            await pipeline.stop()
        })
    })

    describe('stop', () => {
        it('performs a final flush of the accumulated cycle', async () => {
            const pipeline = createPipeline({ flushAt: 100 })

            pipeline.feed(feedBatch([1, 2]))
            await drainNext(pipeline) // fold records into the state; under threshold

            const flushed = await pipeline.stop()
            expect(flushed).toMatchObject({ flushed: true })
            expect(flushedRecords(flushed)).toEqual([1, 2])
        })

        it('returns null when there is nothing accumulated', async () => {
            const pipeline = createPipeline({ flushAt: 100 })
            expect(await pipeline.stop()).toBeNull()
        })
    })

    // An element fed while a flush is in progress binds to a cycle when it is REDUCED, not when it
    // is fed — so it lands in the next cycle's state, never the one being flushed.
    it('a feed during a flush lands in the next cycle', async () => {
        const pipeline = createPipeline({ flushAt: 100 })

        pipeline.feed(feedBatch([1]))
        const firstFlush = await pipeline.flush()
        expect(flushedRecords(firstFlush)).toEqual([1])

        pipeline.feed(feedBatch([2]))
        const secondFlush = await pipeline.flush()
        expect(flushedRecords(secondFlush)).toEqual([2])
    })
})
