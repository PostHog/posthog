import {
    AccumulatingPipeline,
    AccumulatingResult,
    BeforeCycleInput,
    BeforeCycleOutput,
    CycleFlushInput,
} from './accumulating-pipeline'
import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { createOkContext } from './helpers'
import { Pipeline } from './pipeline.interface'
import { PipelineResultType, dlq, drop, isOkResult, ok } from './results'

type RecordIn = { id: number }
// The cycle context carries its own accumulator array, like SessionBatchRecorder.
type Batch = { records: number[] }

// Flush pipeline: receives the cycle flush input (one element) and emits the cycle context's
// accumulated records.
class RecordsFlushPipeline
    implements ChunkPipeline<CycleFlushInput<RecordIn, Batch>, number[], Record<string, never>, Record<string, never>>
{
    private buffer: OkResultWithContext<CycleFlushInput<RecordIn, Batch>, Record<string, never>>[] = []

    feed(elements: OkResultWithContext<CycleFlushInput<RecordIn, Batch>, Record<string, never>>[]): void {
        this.buffer.push(...elements)
    }

    next(): Promise<ChunkPipelineResultWithContext<number[], Record<string, never>> | null> {
        if (this.buffer.length === 0) {
            return Promise.resolve(null)
        }
        const out = this.buffer
        this.buffer = []
        return Promise.resolve(
            out.map((element) => ({
                result: ok(element.result.value.cycleContext.records),
                context: element.context,
            }))
        )
    }
}

// Concatenates the records emitted by RecordsFlushPipeline out of a flushed result.
function flushedRecords(result: AccumulatingResult<RecordIn, number[], Record<string, never>> | null): number[] {
    if (!result || !result.flushed) {
        return []
    }
    return result.elements.flatMap((element) => (isOkResult(element.result) ? element.result.value : []))
}

function feedBatch(ids: number[]): OkResultWithContext<RecordIn, Record<string, never>>[] {
    return ids.map((id) => createOkContext({ id }, {}))
}

// Folds each fed element's id into the accumulator carried on its (tagged) value, then re-emits the
// element — a plain chunk pipeline, like the session-replay record pipeline folding into the
// recorder. Negative ids come out as drop results (they still accumulate — the flush must see every
// message's row). `sideEffectPerDrain`, when set, is attached to the first emitted element's context
// per drain, so tests can assert the accumulating pipeline lifts element side effects into the turn.
class FoldingRecordPipeline
    implements ChunkPipeline<RecordIn & Batch, RecordIn, Record<string, never>, Record<string, never>>
{
    private buffer: OkResultWithContext<RecordIn & Batch, Record<string, never>>[] = []

    constructor(private sideEffectPerDrain?: () => Promise<unknown>) {}

    feed(elements: OkResultWithContext<RecordIn & Batch, Record<string, never>>[]): void {
        this.buffer.push(...elements)
    }

    next(): Promise<ChunkPipelineResultWithContext<RecordIn, Record<string, never>> | null> {
        if (this.buffer.length === 0) {
            return Promise.resolve(null)
        }
        const out = this.buffer
        this.buffer = []
        for (const element of out) {
            if (isOkResult(element.result) && element.result.value.id >= 0) {
                element.result.value.records.push(element.result.value.id)
            }
        }
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
    let beforeCycle: jest.Mock

    function createPipeline(options: {
        flushAt: number
        maxCycleAgeMs?: number
        recordSideEffect?: () => Promise<unknown>
    }) {
        beforeCycle = jest.fn((input: OkResultWithContext<BeforeCycleInput, Record<string, never>>) =>
            Promise.resolve(
                createOkContext<BeforeCycleOutput<Batch>>(
                    { cycleContext: { records: [], cycleId: input.result.value.cycleId } },
                    {}
                )
            )
        )
        const beforePipeline = { process: beforeCycle } as unknown as Pipeline<
            BeforeCycleInput,
            BeforeCycleOutput<Batch>,
            Record<string, never>
        >

        return new AccumulatingPipeline<
            RecordIn,
            RecordIn,
            Record<string, never>,
            Record<string, never>,
            Batch,
            number[],
            Record<string, never>
        >({
            beforeCycle: beforePipeline,
            pipeline: new FoldingRecordPipeline(options.recordSideEffect),
            shouldFlush: (cycleContext) => cycleContext.records.length >= options.flushAt,
            maxCycleAgeMs: options.maxCycleAgeMs ?? 60_000,
            flushPipeline: new RecordsFlushPipeline(),
        })
    }

    async function drainNext(pipeline: ReturnType<typeof createPipeline>) {
        return await pipeline.next()
    }

    it('accumulates across feeds and does not flush under the size threshold', async () => {
        const pipeline = createPipeline({ flushAt: 5 })

        await pipeline.feed(feedBatch([1, 2]))
        const recorded = await drainNext(pipeline)
        await pipeline.feed(feedBatch([3]))
        await drainNext(pipeline)

        expect(recorded).toEqual({ flushed: false, elements: expect.any(Array), sideEffects: [] })
        // record drained, accumulator under threshold → next() finds nothing to flush
        expect(await drainNext(pipeline)).toBeNull()
        // beforeCycle ran exactly once (no flush → no re-mint)
        expect(beforeCycle).toHaveBeenCalledTimes(1)
    })

    it('flushes on the size trigger and re-mints the accumulator', async () => {
        const pipeline = createPipeline({ flushAt: 3 })

        await pipeline.feed(feedBatch([1, 2, 3]))
        const recorded = await drainNext(pipeline)
        expect(recorded).toMatchObject({ flushed: false })

        const flushed = await drainNext(pipeline)
        expect(flushed).toMatchObject({ flushed: true })
        expect(flushedRecords(flushed)).toEqual([1, 2, 3])
        // re-mint: beforeCycle ran for the initial cycle and again after the flush
        expect(beforeCycle).toHaveBeenCalledTimes(2)
    })

    it('emits record results first, then the flush on the next call', async () => {
        const pipeline = createPipeline({ flushAt: 2 })

        await pipeline.feed(feedBatch([1, 2]))

        const first = await drainNext(pipeline)
        expect(first).toMatchObject({ flushed: false })

        const second = await drainNext(pipeline)
        expect(second).toMatchObject({ flushed: true })

        expect(await drainNext(pipeline)).toBeNull()
    })

    it('returns null when there is nothing to record and nothing to flush', async () => {
        const pipeline = createPipeline({ flushAt: 5 })
        expect(await drainNext(pipeline)).toBeNull()
        expect(beforeCycle).not.toHaveBeenCalled()
    })

    // Every drained result accumulates as a bare result — non-OK included, since downstream
    // bookkeeping (e.g. the offsets a flush commits) must cover dropped messages too.
    it('accumulates non-OK results alongside OK ones, as bare results', async () => {
        const pipeline = createPipeline({ flushAt: 100 })

        await pipeline.feed(feedBatch([1, -2, 3]))
        const recorded = await drainNext(pipeline)

        const elements = recorded && !recorded.flushed ? recorded.elements : []
        expect(elements.map((r) => r.type)).toEqual([
            PipelineResultType.OK,
            PipelineResultType.DROP,
            PipelineResultType.OK,
        ])
        expect(elements.map((r) => (isOkResult(r) ? r.value.id : null))).toEqual([1, null, 3])
    })

    it('surfaces the record elements side effects on a record turn', async () => {
        const recordSideEffect = jest.fn().mockResolvedValue(undefined)
        const pipeline = createPipeline({ flushAt: 100, recordSideEffect })

        await pipeline.feed(feedBatch([1, 2]))
        const recorded = await drainNext(pipeline)

        expect(recorded).toMatchObject({ flushed: false })
        expect(recorded?.sideEffects).toHaveLength(1)
    })

    // Contexts (and the side effects on them) are dropped at drain time — the flush must not
    // re-surface a produce that already surfaced on its record turn.
    it('lifts element side effects once — the flush turn does not re-surface them', async () => {
        const recordSideEffect = jest.fn().mockResolvedValue(undefined)
        const pipeline = createPipeline({ flushAt: 100, recordSideEffect })

        await pipeline.feed(feedBatch([1]))
        const recorded = await drainNext(pipeline)
        expect(recorded?.sideEffects).toHaveLength(1)

        const flushed = await pipeline.stop()
        expect(flushed).toMatchObject({ flushed: true })
        expect(flushed?.sideEffects).toEqual([])
    })

    it('flush() drains buffered records and flushes immediately, below the size threshold', async () => {
        const pipeline = createPipeline({ flushAt: 100 })

        await pipeline.feed(feedBatch([1, 2]))
        // No next() drain: flush() must fold the buffered records in itself before flushing.
        const flushed = await pipeline.flush()

        expect(flushed).toMatchObject({ flushed: true })
        expect(flushedRecords(flushed)).toEqual([1, 2])
        // the cycle was re-minted; a forced flush still emits a flushed result, now with no records
        // (so the consumer always gets a flush signal, even for an empty cycle)
        const empty = await pipeline.flush()
        expect(empty).toMatchObject({ flushed: true })
        expect(flushedRecords(empty)).toEqual([])
    })

    describe('age timer', () => {
        beforeEach(() => jest.useFakeTimers())
        afterEach(() => jest.useRealTimers())

        it('flushes a buffered cycle once the age elapses with no further feeds (idle topic)', async () => {
            const pipeline = createPipeline({ flushAt: 100, maxCycleAgeMs: 1000 })
            pipeline.start()

            await pipeline.feed(feedBatch([1]))
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
            await pipeline.feed(feedBatch([1]))
            await drainNext(pipeline)
            const sizeFlush = await drainNext(pipeline)
            expect(sizeFlush).toMatchObject({ flushed: true })

            // less than maxCycleAgeMs since that flush, empty accumulator → no age flush
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

            await pipeline.feed(feedBatch([1, 2]))
            await drainNext(pipeline) // fold records into accumulator; under threshold

            const flushed = await pipeline.stop()
            expect(flushed).toMatchObject({ flushed: true })
            expect(flushedRecords(flushed)).toEqual([1, 2])
        })

        it('returns null when there is nothing accumulated', async () => {
            const pipeline = createPipeline({ flushAt: 100 })
            expect(await pipeline.stop()).toBeNull()
        })
    })

    it('serializes feed against a concurrent flush re-mint so records are not lost', async () => {
        // beforeCycle for the first re-mint (cycleId 1) blocks on a gate, so we can deterministically
        // issue a feed() while a flush() is mid re-mint and assert the fed record lands in the new cycle.
        let cycleSeq = 0
        const gate: { open: (() => void) | null } = { open: null }
        const makeContext = (cycleId: number) =>
            createOkContext<BeforeCycleOutput<Batch>>({ cycleContext: { records: [], cycleId } }, {})
        const beforeProcess = jest.fn((input: OkResultWithContext<BeforeCycleInput, Record<string, never>>) => {
            const seq = cycleSeq++
            const cycleId = input.result.value.cycleId
            if (seq === 1) {
                return new Promise((resolve) => {
                    gate.open = () => resolve(makeContext(cycleId))
                })
            }
            return Promise.resolve(makeContext(cycleId))
        })
        const beforePipeline = { process: beforeProcess } as unknown as Pipeline<
            BeforeCycleInput,
            BeforeCycleOutput<Batch>,
            Record<string, never>
        >
        const pipeline = new AccumulatingPipeline<
            RecordIn,
            RecordIn,
            Record<string, never>,
            Record<string, never>,
            Batch,
            number[],
            Record<string, never>
        >({
            beforeCycle: beforePipeline,
            pipeline: new FoldingRecordPipeline(),
            shouldFlush: () => false,
            maxCycleAgeMs: 60_000,
            flushPipeline: new RecordsFlushPipeline(),
        })

        await pipeline.feed(feedBatch([1]))

        // flush() drains record [1], flushes it, then blocks on the re-mint gate while holding the mutex.
        const flushPromise = pipeline.flush()
        while (gate.open === null) {
            await new Promise((resolve) => setImmediate(resolve))
        }

        // Issued while the flush is mid re-mint: must queue behind it, not tag the cycle being flushed.
        const feedPromise = pipeline.feed(feedBatch([2]))
        gate.open()

        const firstFlush = await flushPromise
        await feedPromise

        expect(flushedRecords(firstFlush)).toEqual([1])

        const secondFlush = await pipeline.flush()
        expect(flushedRecords(secondFlush)).toEqual([2])
    })

    it('throws when beforeCycle returns a non-ok result', async () => {
        beforeCycle = jest.fn(() =>
            Promise.resolve({
                result: dlq<BeforeCycleOutput<Batch>>('boom', new Error('boom')),
                context: { sideEffects: [], warnings: [] },
            })
        )
        const beforePipeline = { process: beforeCycle } as unknown as Pipeline<
            BeforeCycleInput,
            BeforeCycleOutput<Batch>,
            Record<string, never>
        >
        const pipeline = new AccumulatingPipeline<
            RecordIn,
            RecordIn,
            Record<string, never>,
            Record<string, never>,
            Batch,
            number[],
            Record<string, never>
        >({
            beforeCycle: beforePipeline,
            pipeline: new FoldingRecordPipeline(),
            shouldFlush: () => false,
            maxCycleAgeMs: 60_000,
            flushPipeline: new RecordsFlushPipeline(),
        })

        await expect(pipeline.feed(feedBatch([1]))).rejects.toThrow('beforeCycle returned non-ok result')
    })
})
