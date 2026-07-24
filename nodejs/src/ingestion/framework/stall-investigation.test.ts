import { Message } from 'node-rdkafka'

import { BatchingPipeline } from './batching-pipeline'
import { newBatchingPipeline } from './builders/helpers'
import { OkResultWithContext } from './chunk-pipeline.interface'
import { PipelineResultWithContext } from './pipeline.interface'
import { drop, ok } from './results'

// Liveness tests for the analytics pipeline composition: BatchingPipeline over
// filterMap(gather + batch steps + groupBy/concurrently), driven by concurrent
// feed/drain callers like the ingestion API server. These hunt for stalls (lost
// wakeups, stranded messages) rather than asserting specific outputs.

interface Item {
    key: string
    id: number
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

function makeBatch(items: Item[]): OkResultWithContext<Item, MsgCtx>[] {
    return items.map((item) => ({
        result: ok(item),
        context: {
            message: makeMessage(item.id),
            lastStep: undefined,
            sideEffects: [],
            warnings: [],
        },
    }))
}

// Deterministic PRNG so a failing seed reproduces exactly.
function mulberry32(seed: number): () => number {
    let a = seed >>> 0
    return () => {
        a = (a + 0x6d2b79f5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

// Randomized scheduling perturbation: sometimes stay synchronous, sometimes yield
// a microtask/macrotask so feeds land at different await points of parked drains.
async function randomYield(rng: () => number): Promise<void> {
    const r = rng()
    if (r < 0.35) {
        return
    }
    if (r < 0.65) {
        await Promise.resolve()
        return
    }
    if (r < 0.9) {
        await new Promise((resolve) => setTimeout(resolve, 0))
        return
    }
    await new Promise((resolve) => setTimeout(resolve, 1))
}

async function withWatchdog<T>(promise: Promise<T>, ms: number, diagnostics: () => string): Promise<T> {
    let timer: NodeJS.Timeout | undefined
    const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`STALL DETECTED after ${ms}ms: ${diagnostics()}`)), ms)
    })
    try {
        return await Promise.race([promise, timeout])
    } finally {
        clearTimeout(timer)
    }
}

describe('analytics pipeline shape liveness', () => {
    // Mirrors the joined ingestion pipeline shape (joined-ingestion-pipeline.ts):
    // messageAware sequential steps → filterMap(gather → batch steps → groupBy →
    // concurrently(sequential per-item)) under a BatchingPipeline.
    function buildPipeline(
        rng: () => number,
        concurrentBatches: number,
        processedByKey: Map<string, number[]>,
        options?: {
            failOnId?: number
            // Probability a pre-gather step drops an item (exercises FilterMap's
            // immediate-emit path for non-OK results).
            earlyDropRate?: number
            // Probability the per-item group processor drops an item.
            lateDropRate?: number
            // Probability the per-item group processor fails transiently once
            // (exercises the retry wrapper's sleep/backoff timing).
            transientFailRate?: number
            maxConcurrency?: number
        }
    ): BatchingPipeline<Item, Item, MsgCtx, any, any, never> {
        const failedOnce = new Set<number>()
        return newBatchingPipeline<Item, Item, MsgCtx>(
            (b) => b.pipe((input) => Promise.resolve(ok(input))),
            (batch) =>
                batch
                    .sequentially((b) =>
                        b.pipe(async (value: Item) => {
                            await randomYield(rng)
                            if (rng() < (options?.earlyDropRate ?? 0)) {
                                return drop<Item>('fuzz early drop')
                            }
                            return ok(value)
                        })
                    )
                    .filterMap(
                        (element) => element,
                        (b) =>
                            b
                                .gather()
                                .pipeChunk(async (values: Item[]) => {
                                    await randomYield(rng)
                                    return values.map((value) => ok(value))
                                })
                                .concurrentlyPerGroup(
                                    (value) => value.key,
                                    (group) =>
                                        group.sequentially((event) =>
                                            event.pipe(
                                                async (value: Item) => {
                                                    await randomYield(rng)
                                                    if (options?.failOnId === value.id) {
                                                        throw new Error(`poison item ${value.id}`)
                                                    }
                                                    if (
                                                        rng() < (options?.transientFailRate ?? 0) &&
                                                        !failedOnce.has(value.id)
                                                    ) {
                                                        failedOnce.add(value.id)
                                                        const transient: Error & { isRetriable?: boolean } = new Error(
                                                            `transient failure ${value.id}`
                                                        )
                                                        transient.isRetriable = true
                                                        throw transient
                                                    }
                                                    if (rng() < (options?.lateDropRate ?? 0)) {
                                                        return drop<Item>('fuzz late drop')
                                                    }
                                                    let seen = processedByKey.get(value.key)
                                                    if (!seen) {
                                                        seen = []
                                                        processedByKey.set(value.key, seen)
                                                    }
                                                    seen.push(value.id)
                                                    return ok(value)
                                                },
                                                { retry: { tries: 3, sleepMs: 1, name: 'fuzz_per_item' } }
                                            )
                                        ),
                                    { maxConcurrency: options?.maxConcurrency }
                                )
                    ),
            (b) => b.pipe((input) => Promise.resolve(ok(input))),
            { concurrentBatches }
        )
    }

    // Count every emitted element (OK or not) by its Kafka message offset, which
    // makeBatch sets to the item id — dropped items must still be accounted for.
    function collectEmitted(elements: PipelineResultWithContext<Item, any>[], emitted: number[]): void {
        for (const element of elements) {
            emitted.push(Number(element.context.message.offset))
        }
    }

    // H1: hunt for lost wakeups. Concurrent handlers feed and drain the shared
    // pipeline like the ingestion API server does. Every fed message must come
    // back out; the watchdog converts a stall into a failure naming the seed.
    it('emits every fed message under concurrent feed/drain drivers (fuzz)', async () => {
        const HANDLERS = 3
        const ROUNDS = 5
        const KEYSPACE = ['a', 'b', 'c', 'd']

        for (let seed = 1; seed <= 40; seed++) {
            const rng = mulberry32(seed)
            const processedByKey = new Map<string, number[]>()
            // Rotate the group-concurrency cap: unbounded (analytics), 1, and 2
            // (the bounded variants added in the recent refactor).
            const maxConcurrency = [undefined, 1, 2][seed % 3]
            const pipeline = buildPipeline(rng, HANDLERS, processedByKey, {
                earlyDropRate: 0.08,
                lateDropRate: 0.08,
                transientFailRate: 0.05,
                maxConcurrency,
            })

            const emitted: number[] = []
            const fed: number[] = []
            let nextId = 0

            const handlers = Array.from({ length: HANDLERS }, async () => {
                for (let round = 0; round < ROUNDS; round++) {
                    const size = 1 + Math.floor(rng() * 8)
                    const items: Item[] = []
                    for (let i = 0; i < size; i++) {
                        const id = nextId++
                        items.push({ key: KEYSPACE[Math.floor(rng() * KEYSPACE.length)], id })
                        fed.push(id)
                    }
                    const feedResult = await pipeline.feed(makeBatch(items))
                    if (!feedResult.ok) {
                        throw new Error(`feed rejected: ${feedResult.reason}`)
                    }
                    let result = await pipeline.next()
                    while (result !== null) {
                        collectEmitted(result.elements, emitted)
                        result = await pipeline.next()
                    }
                    await randomYield(rng)
                }
            })

            await withWatchdog(
                Promise.all(handlers),
                5000,
                () =>
                    `seed=${seed} fed=${fed.length} emitted=${emitted.length} missing=[${fed.filter((id) => !emitted.includes(id)).join(',')}]`
            )

            expect([...emitted].sort((x, y) => x - y)).toEqual([...fed].sort((x, y) => x - y))
        }
    }, 180000)

    // H2: the grouping stage's per-key state is shared across concurrent batches.
    // A key busy with batch A's slow group must still process batch B's items for
    // the same key (queued, restarted on completion) in feed order.
    it('processes items for a group key spanning two concurrent batches, in order', async () => {
        const processedByKey = new Map<string, number[]>()
        let releaseFirstGroup!: () => void
        const firstGroupGate = new Promise<void>((resolve) => {
            releaseFirstGroup = resolve
        })

        const pipeline = newBatchingPipeline<Item, Item, MsgCtx>(
            (b) => b.pipe((input) => Promise.resolve(ok(input))),
            (batch) =>
                batch.filterMap(
                    (element) => element,
                    (b) =>
                        b.gather().concurrentlyPerGroup(
                            (value) => value.key,
                            (group) =>
                                group.sequentially((event) =>
                                    event.pipe(async (value: Item) => {
                                        if (value.id === 0) {
                                            await firstGroupGate
                                        }
                                        let seen = processedByKey.get(value.key)
                                        if (!seen) {
                                            seen = []
                                            processedByKey.set(value.key, seen)
                                        }
                                        seen.push(value.id)
                                        return ok(value)
                                    })
                                )
                        )
                ),
            (b) => b.pipe((input) => Promise.resolve(ok(input))),
            { concurrentBatches: 2 }
        )

        const emitted: number[] = []
        const drain = async (): Promise<void> => {
            let result = await pipeline.next()
            while (result !== null) {
                collectEmitted(result.elements, emitted)
                result = await pipeline.next()
            }
        }

        // Batch 1: key K blocked on the gate, key L free.
        expect(
            (
                await pipeline.feed(
                    makeBatch([
                        { key: 'K', id: 0 },
                        { key: 'L', id: 1 },
                    ])
                )
            ).ok
        ).toBe(true)
        const drainA = drain()

        // Let batch 1's groups start and park on the gate.
        await new Promise((resolve) => setTimeout(resolve, 10))

        // Batch 2: more items for the busy key K.
        expect(
            (
                await pipeline.feed(
                    makeBatch([
                        { key: 'K', id: 2 },
                        { key: 'K', id: 3 },
                    ])
                )
            ).ok
        ).toBe(true)
        const drainB = drain()

        await new Promise((resolve) => setTimeout(resolve, 10))
        releaseFirstGroup()

        await withWatchdog(
            Promise.all([drainA, drainB]),
            5000,
            () => `emitted=[${emitted.join(',')}] processedK=[${(processedByKey.get('K') ?? []).join(',')}]`
        )

        expect([...emitted].sort((x, y) => x - y)).toEqual([0, 1, 2, 3])
        expect(processedByKey.get('K')).toEqual([0, 2, 3])
    })

    // H6 (fixed): an empty feed used to register a zero-message batch that could
    // never complete — corruption throw on the next drain, then the phantom
    // batch held its concurrency slot forever (every later feed at_capacity).
    // feedSerialized now skips empty feeds entirely; this guards that fix.
    it('empty feed is a no-op: no corruption, no leaked capacity slot', async () => {
        const processedByKey = new Map<string, number[]>()
        const rng = mulberry32(7)
        const pipeline = buildPipeline(rng, 1, processedByKey)

        expect((await pipeline.feed([])).ok).toBe(true)
        expect(await withWatchdog(pipeline.next(), 5000, () => 'drain after empty feed')).toBeNull()

        // No phantom batch occupies the (single) slot: a real feed goes through
        // and completes.
        expect((await pipeline.feed(makeBatch([{ key: 'a', id: 0 }]))).ok).toBe(true)
        const emitted: number[] = []
        let result = await withWatchdog(pipeline.next(), 5000, () => 'drain after real feed')
        while (result !== null) {
            collectEmitted(result.elements, emitted)
            result = await withWatchdog(pipeline.next(), 5000, () => 'drain after real feed')
        }
        expect(emitted).toEqual([0])
    })

    // H3: a processor throw poisons the shared pipeline permanently and the failed
    // batch keeps occupying a concurrency slot. This pins the wedge mechanism: a
    // driver that swallows the rejection instead of crashing ends up with every
    // feed rejected at_capacity — a silent stall from the outside.
    it('poisoned pipeline rejects next() forever and leaks batch capacity', async () => {
        const processedByKey = new Map<string, number[]>()
        const rng = mulberry32(42)
        const pipeline = buildPipeline(rng, 2, processedByKey, { failOnId: 1 })

        expect(
            (
                await pipeline.feed(
                    makeBatch([
                        { key: 'a', id: 0 },
                        { key: 'b', id: 1 },
                    ])
                )
            ).ok
        ).toBe(true)

        const drainAll = async (): Promise<void> => {
            let result = await pipeline.next()
            while (result !== null) {
                result = await pipeline.next()
            }
        }
        await expect(withWatchdog(drainAll(), 5000, () => 'drain of poisoned batch')).rejects.toThrow('poison item 1')

        // The pipeline is poisoned: draining again still rejects.
        await expect(withWatchdog(drainAll(), 5000, () => 'second drain')).rejects.toThrow('poison item 1')

        // The failed batch still occupies a slot; one more feed fits, then capacity.
        expect((await pipeline.feed(makeBatch([{ key: 'c', id: 2 }]))).ok).toBe(true)
        const thirdFeed = await pipeline.feed(makeBatch([{ key: 'd', id: 3 }]))
        expect(thirdFeed.ok).toBe(false)
        if (!thirdFeed.ok) {
            expect(thirdFeed.kind).toBe('at_capacity')
        }
    })
})
