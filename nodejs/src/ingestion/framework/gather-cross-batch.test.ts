import { Message } from 'node-rdkafka'

import { newBatchingPipeline } from './builders/helpers'
import { OkResultWithContext } from './chunk-pipeline.interface'
import { GatherOptions } from './gathering-chunk-pipeline'
import { isOkResult, ok } from './results'

// Cross-batch behavior of gather() under concurrentBatches > 1 (the ingestion
// API server path), on the analytics pipeline shape
// (joined-ingestion-pipeline.ts → post-team-preprocessing-subpipeline.ts):
//
//   sequentially(parse/team) → filterMap( sequentially(validation) → gather()
//     → pipeChunk(cookieless, prefetch, …) → concurrentlyPerGroup(per-distinct-id) )
//
// All concurrent batches share this one pipeline instance, and a batch fed
// while an earlier batch's pre-gather step is in flight lands in the same
// gather drain. The two tests pin the two emission policies on that exact
// interleaving:
// - barrier (default): the drain waits for ALL in-flight work, so batch A's
//   per-group processing and completion are gated on batch B's pre-gather
//   step, and the emitted chunk spans both batches.
// - bounded (what analytics/AI use): batch A's already-completed results are
//   emitted within maxWaitMs and A completes while batch B is still parked
//   pre-gather; B follows in its own chunk. Coalescing is kept, the
//   unbounded barrier is not.
interface Item {
    key: string
    id: string
}

type MsgCtx = { message: Message }

function makeMessage(offset: number): Message {
    return {
        topic: 'test-topic',
        partition: 0,
        offset,
        size: 0,
        key: Buffer.from(`key${offset}`),
        value: Buffer.from(`value${offset}`),
        timestamp: Date.now(),
    }
}

let nextOffset = 0
function makeBatch(items: Item[]): OkResultWithContext<Item, MsgCtx>[] {
    return items.map((item) => ({
        result: ok(item),
        context: {
            message: makeMessage(nextOffset++),
            lastStep: undefined,
            sideEffects: [],
            warnings: [],
        },
    }))
}

interface Gate {
    entered: Promise<void>
    markEntered: () => void
    released: Promise<void>
    release: () => void
}

function makeGate(): Gate {
    let markEntered!: () => void
    let release!: () => void
    const entered = new Promise<void>((resolve) => (markEntered = resolve))
    const released = new Promise<void>((resolve) => (release = resolve))
    return { entered, markEntered, released, release }
}

function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0))
}

async function withWatchdog<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
    let timer: NodeJS.Timeout | undefined
    const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`stall after ${ms}ms: ${label}`)), ms)
    })
    try {
        return await Promise.race([promise, timeout])
    } finally {
        clearTimeout(timer)
    }
}

describe('gather() across concurrent batches', () => {
    interface Harness {
        pipeline: ReturnType<typeof buildPipeline>['pipeline']
        gates: Map<string, Gate>
        gatherChunks: string[][]
        groupProcessed: string[]
        completedBatches: string[][]
        onBatchCompleted: () => void
    }

    function buildPipeline(gatherOptions?: GatherOptions) {
        const gates = new Map<string, Gate>()
        const gatherChunks: string[][] = []
        const groupProcessed: string[] = []

        // Pre-gather per-item step (mirrors the validation sequentially-block
        // ahead of gather() in the post-team subpipeline).
        const preGatherStep = async (value: Item): Promise<ReturnType<typeof ok<Item>>> => {
            const gate = gates.get(value.id)
            if (gate) {
                gate.markEntered()
                await gate.released
            }
            return ok(value)
        }

        const pipeline = newBatchingPipeline<Item, Item, MsgCtx>(
            (b) => b.pipe((input) => Promise.resolve(ok(input))),
            (batch) =>
                batch
                    // Outer per-item steps (parse / team resolution).
                    .sequentially((b) => b.pipe((value: Item) => Promise.resolve(ok(value))))
                    .filterMap(
                        (element) => element,
                        (b) =>
                            b
                                .sequentially((pre) => pre.pipe(preGatherStep))
                                .gather(gatherOptions)
                                // Chunk step after gather (cookieless & co.): records
                                // what each emitted chunk actually contains.
                                .pipeChunk((values: Item[]) => {
                                    gatherChunks.push(values.map((value) => value.id))
                                    return Promise.resolve(values.map((value) => ok(value)))
                                })
                                .concurrentlyPerGroup(
                                    (value) => value.key,
                                    (group) =>
                                        group.sequentially((event) =>
                                            event.pipe((value: Item) => {
                                                groupProcessed.push(value.id)
                                                return Promise.resolve(ok(value))
                                            })
                                        )
                                )
                    ),
            (b) => b.pipe((input) => Promise.resolve(ok(input))),
            { concurrentBatches: 2 }
        )

        return { pipeline, gates, gatherChunks, groupProcessed }
    }

    // Feeds batch A (its element gated pre-gather), starts the drain, then
    // feeds batch B (also gated) mid-drain and releases A. Returns once B has
    // provably been pulled into the same drain (its gate is entered).
    async function runInterleaving(harness: Omit<Harness, 'completedBatches' | 'onBatchCompleted'>): Promise<{
        completedBatches: string[][]
        firstBatchCompleted: Promise<void>
        drainDone: Promise<void>
        gateB: Gate
    }> {
        const { pipeline, gates } = harness
        const gateA = makeGate()
        const gateB = makeGate()
        gates.set('a1', gateA)
        gates.set('b1', gateB)

        const completedBatches: string[][] = []
        let markFirstBatchCompleted!: () => void
        const firstBatchCompleted = new Promise<void>((resolve) => (markFirstBatchCompleted = resolve))

        expect((await pipeline.feed(makeBatch([{ key: 'a', id: 'a1' }]))).ok).toBe(true)
        const drainDone = (async () => {
            let result = await pipeline.next()
            while (result !== null) {
                completedBatches.push(
                    result.elements.map((element) => (isOkResult(element.result) ? element.result.value.id : 'non-ok'))
                )
                if (completedBatches.length === 1) {
                    markFirstBatchCompleted()
                }
                result = await pipeline.next()
            }
        })()
        await withWatchdog(gateA.entered, 5000, 'batch A never reached the pre-gather step')

        // Batch B lands while A is mid pre-gather; its element is routed into
        // the gather's upstream before the drain finishes.
        expect((await pipeline.feed(makeBatch([{ key: 'b', id: 'b1' }]))).ok).toBe(true)
        await settle()

        // A clears its own pre-gather work entirely…
        gateA.release()
        // …and the same gather drain moves on to pulling batch B's element.
        await withWatchdog(gateB.entered, 5000, 'gather drain never pulled batch B')
        await settle()

        return { completedBatches, firstBatchCompleted, drainDone, gateB }
    }

    it("barrier (default): couples a batch's completion to a later concurrent batch's pre-gather processing", async () => {
        const harness = buildPipeline()
        const { completedBatches, drainDone, gateB } = await runInterleaving(harness)

        // Batch A has finished everything it needs pre-gather, yet its
        // per-group processing has not started and the batch cannot complete:
        // it is gated on batch B's pre-gather step.
        expect(harness.groupProcessed).toEqual([])
        expect(completedBatches).toEqual([])

        gateB.release()
        await withWatchdog(drainDone, 5000, 'pipeline never drained after releasing batch B')

        // The gather emitted ONE chunk spanning both batches.
        expect(harness.gatherChunks).toEqual([['a1', 'b1']])
        expect(completedBatches.flat().sort()).toEqual(['a1', 'b1'])
    })

    it('bounded: batch A completes while batch B is still parked pre-gather; chunks stay per-ready-set', async () => {
        const harness = buildPipeline({ maxWaitMs: 50, minItems: 1000 })
        const { completedBatches, firstBatchCompleted, drainDone, gateB } = await runInterleaving(harness)

        // Batch A's element is emitted, group-processed, and the batch
        // completes — while batch B is still parked in its pre-gather step.
        await withWatchdog(firstBatchCompleted, 5000, 'batch A did not complete while batch B was parked')
        expect(harness.groupProcessed).toEqual(['a1'])
        expect(completedBatches).toEqual([['a1']])
        expect(harness.gatherChunks).toEqual([['a1']])

        gateB.release()
        await withWatchdog(drainDone, 5000, 'pipeline never drained after releasing batch B')

        // B follows in its own chunk; nothing lost, nothing duplicated.
        expect(harness.gatherChunks).toEqual([['a1'], ['b1']])
        expect(harness.groupProcessed.sort()).toEqual(['a1', 'b1'])
        expect(completedBatches.flat().sort()).toEqual(['a1', 'b1'])
    })
})
