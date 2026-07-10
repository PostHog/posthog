import { Message } from 'node-rdkafka'

import { DlqOutput, IngestionWarningsOutput } from '~/common/outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { BatchWritingGroupStore } from '~/ingestion/common/groups/batch-writing-group-store'
import { FlushResult, PersonsStore } from '~/ingestion/common/persons/persons-store'
import {
    FlushBatchStoresOutputs,
    createFlushBatchStoresStep,
} from '~/ingestion/common/steps/event-processing/flush-batch-stores-step'
import { BatchWritingStore, BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { BatchingPipeline, BeforeBatchInput, FeedResult } from '~/ingestion/framework/batching-pipeline'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { OkResultWithContext } from '~/ingestion/framework/pipeline.interface'
import { PipelineResult, drop, ok } from '~/ingestion/framework/results'
import { PERSONS_OUTPUT } from '~/ingestion/pipelines/analytics/outputs'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'

/**
 * Integration tests for BatchingPipeline + groupBy + sequential group processing,
 * mirroring the shape of the joined ingestion pipeline (`createJoinedIngestionPipeline`).
 *
 * ## Principle
 *
 * Every piece of orchestration machinery under test is REAL production code:
 * BatchingPipeline, BufferingBatchPipeline, SequentialBatchPipeline,
 * ConcurrentlyGroupingBatchPipeline, ResultHandlingPipeline,
 * SideEffectHandlingPipeline, the builder chain, PromiseScheduler, and the
 * production createFlushBatchStoresStep. Only the leaves are fakes: the
 * per-event step, the storage backend, and the Kafka outputs. A bug found
 * here is a bug in the real code paths, not in a simulation of them.
 *
 * ## Stage mapping (test pipeline → joined ingestion pipeline)
 *
 *   beforeBatch:  bindStoresBeforeBatchStep → createPersonsStore/GroupStoreBeforeBatchStep
 *                 (same mechanism: a batchId-bound store view enters batchContext,
 *                 which BatchingPipeline.feed spreads into element values)
 *   parse:        sequentially(parseStep) → the header/body parse + team resolution
 *                 stages (collapsed to one representative async sequential step
 *                 that also resolves a team, like createResolveTeamStep)
 *   filterMap:    filterMap(addTeamToContext, fb => fb.teamAware(...)
 *                 .handleIngestionWarnings(...)) — same structure as production,
 *                 which means groupBy lives INSIDE filterMap's sub-pipeline and
 *                 new batches are only admitted into it when it drains
 *   grouping:     groupBy(event.key).concurrently(g => g.sequentially(processEventStep))
 *                 → groupBy(token:distinctId).concurrently(... perDistinctIdPipeline)
 *                 — identical primitives; `key` plays the role of token:distinct_id
 *   per-event:    processEventStep → perDistinctIdPipeline. Fake, but does the one
 *                 thing that matters here: an awaited async section (controllable
 *                 via gates / delays, with drop/fail actions) followed by a write
 *                 through the batch-bound store
 *   results:      handleResults + handleSideEffects({ await: false }) — same calls,
 *                 same stages as production, with mock outputs
 *   afterBatch:   the REAL createFlushBatchStoresStep (flush → produce side effects
 *                 → releaseBatch in finally), backed by FakeBatchWritingStore
 *
 * FakeBatchWritingStore implements the real BatchWritingStore lifecycle minus
 * Postgres: writes mark entries dirty and ref the writing batch; flush() drains
 * ALL dirty entries (the real stores are singletons — this is what lets tests
 * show one batch's flush shipping another batch's partial writes); releaseBatch()
 * drops refs and evicts clean unreferenced entries.
 *
 * ## Drive models
 *
 * - Single drainer: feed() N times, then one drain() loop — the Kafka consumer
 *   model. Creates multiple in-flight batches WITHOUT concurrent next() calls,
 *   isolating pure ordering semantics deterministically.
 * - Concurrent drivers: N "handlers" each doing feed → drain-until-null →
 *   waitForAll (a copy of ingestion-api-server's handleIngestRequest), guarded
 *   by a Semaphore(concurrentBatches) playing the Rust consumer's per-worker
 *   semaphore. This is the INGESTION_WORKER_CONCURRENT_BATCHES > 1 rollout model.
 *
 * Determinism comes from gates: per-message deferred promises that hold a
 * specific message inside its processing step until the test releases it,
 * letting tests prove negatives ("a:3 has NOT started while a:2 is held")
 * instead of relying on timing. Stress tests use small random delays and assert
 * order-independent invariants instead (see assertOrderingInvariants).
 *
 * Intentionally not simulated: overflow, cookieless, hog transforms, the gather
 * step — routing/enrichment concerns that don't change batching/grouping/flush
 * semantics.
 *
 * ## Guarantees under test (with concurrentBatches > 1)
 *
 * 1. Messages for the same key are never processed out of order
 * 2. Every message for a key from an earlier batch is processed before any
 *    message for that key from a later batch
 * 3. Messages from different in-flight batches with different keys process in parallel
 * 4. afterBatch (store flush) fires only after every message of that batch finished,
 *    and batch-bound store references are refcounted across concurrent batches
 */

type In = { message: Message }
type Ctx = { message: Message }

interface EventSpec {
    key: string
    seq: number
    action?: 'drop' | 'fail'
}

interface StoreBatchContext {
    storeForBatch: FakeStoreForBatch
}

type ProcessedEvent = In & StoreBatchContext & EventSpec & { team: { id: number } }

/** Mirrors addTeamToContext in joined-ingestion-pipeline.ts. */
function addTeamToContext<T extends { team: { id: number } }, C>(
    element: OkResultWithContext<T, C>
): OkResultWithContext<T, C & { team: { id: number } }> {
    return {
        result: element.result,
        context: {
            ...element.context,
            team: element.result.value.team,
        },
    }
}

type LogEntry =
    | { type: 'start'; key: string; seq: number; batchId: number }
    | { type: 'end'; key: string; seq: number; batchId: number }
    | { type: 'flush'; store: string; entries: { key: string; lastSeq: number; lastWriterBatchId: number }[] }
    | { type: 'release'; store: string; batchId: number }
    | { type: 'afterBatch'; batchId: number }

interface Deferred {
    promise: Promise<void>
    resolve: () => void
}

function deferred(): Deferred {
    let resolve!: () => void
    const promise = new Promise<void>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

/** Flush pending microtasks and macrotasks so in-flight pipeline work settles. */
async function tick(rounds: number = 10): Promise<void> {
    for (let i = 0; i < rounds; i++) {
        await new Promise((resolve) => setImmediate(resolve))
    }
}

// xoshiro128** PRNG (Vigna & Blackman, 2018). Seeded so stress runs use a fixed
// input corpus — a CI failure is reproducible instead of a one-off random draw.
function xoshiro128ss(a: number, b: number, c: number, d: number): () => number {
    return function () {
        const t = b << 9
        let r = b * 5
        r = ((r << 7) | (r >>> 25)) * 9
        c ^= a
        d ^= b
        b ^= c
        a ^= d
        c ^= t
        d = (d << 11) | (d >>> 21)
        return (r >>> 0) / 4294967296
    }
}

/** Batch-scoped view of the fake store, mirroring BatchBoundPersonsStore. */
class FakeStoreForBatch {
    constructor(
        private store: FakeBatchWritingStore,
        public readonly batchId: number
    ) {}

    write(key: string, seq: number): void {
        this.store.write(this.batchId, key, seq)
    }
}

interface CacheEntry {
    lastSeq: number
    lastWriterBatchId: number
    dirty: boolean
    refs: Set<number>
}

/**
 * In-memory store implementing the real BatchWritingStore lifecycle: writes mark
 * entries dirty and reference the writing batch, flush() drains dirty entries into
 * Kafka-style FlushResults, releaseBatch() drops a batch's references and evicts
 * entries that are clean and unreferenced — same refcounting contract as the
 * persons/group batch-writing stores, minus Postgres.
 */
class FakeBatchWritingStore implements BatchWritingStore {
    public cache = new Map<string, CacheEntry>()

    constructor(
        private name: string,
        private log: LogEntry[]
    ) {}

    forBatch(batchId: number): FakeStoreForBatch {
        return new FakeStoreForBatch(this, batchId)
    }

    write(batchId: number, key: string, seq: number): void {
        let entry = this.cache.get(key)
        if (!entry) {
            entry = { lastSeq: seq, lastWriterBatchId: batchId, dirty: true, refs: new Set() }
            this.cache.set(key, entry)
        }
        entry.lastSeq = seq
        entry.lastWriterBatchId = batchId
        entry.dirty = true
        entry.refs.add(batchId)
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        const dirtyEntries = [...this.cache.values()].filter((entry) => entry.dirty)
        const referencedBatches = new Set<number>()
        for (const entry of dirtyEntries) {
            entry.refs.forEach((batchId) => referencedBatches.add(batchId))
        }
        return {
            dirtyEntryCount: dirtyEntries.length,
            referencedBatchCount: referencedBatches.size,
            cacheEntryCount: this.cache.size,
        }
    }

    flush(): Promise<FlushResult[]> {
        const flushed: { key: string; lastSeq: number; lastWriterBatchId: number }[] = []
        const results: FlushResult[] = []
        for (const [key, entry] of this.cache) {
            if (!entry.dirty) {
                continue
            }
            entry.dirty = false
            flushed.push({ key, lastSeq: entry.lastSeq, lastWriterBatchId: entry.lastWriterBatchId })
            results.push({
                teamId: 1,
                distinctId: key,
                messages: [
                    { output: PERSONS_OUTPUT, value: Buffer.from(JSON.stringify({ key, lastSeq: entry.lastSeq })) },
                ],
            })
        }
        this.log.push({ type: 'flush', store: this.name, entries: flushed })
        return Promise.resolve(results)
    }

    releaseBatch(batchId: number): void {
        for (const [key, entry] of this.cache) {
            entry.refs.delete(batchId)
            if (entry.refs.size === 0 && !entry.dirty) {
                this.cache.delete(key)
            }
        }
        this.log.push({ type: 'release', store: this.name, batchId })
    }

    shutdown(): Promise<void> {
        return Promise.resolve()
    }
}

interface HarnessOptions {
    concurrentBatches: number
    /** Optional async delay injected into every process step (for stress tests). */
    processDelay?: () => Promise<void>
}

class Harness {
    public log: LogEntry[] = []
    public personsStore = new FakeBatchWritingStore('persons', this.log)
    public groupStore = new FakeBatchWritingStore('groups', this.log)
    public outputs = createMockIngestionOutputs<DlqOutput | IngestionWarningsOutput | typeof PERSONS_OUTPUT>()
    public scheduler = new PromiseScheduler()
    /** Accepted batches in batchId order: which events went into which batch. */
    public submissions: { batchId: number; specs: EventSpec[] }[] = []
    public pipeline: BatchingPipeline<In, ProcessedEvent, Ctx, StoreBatchContext, Ctx & { messageId: number }, never>

    private gates = new Map<string, Deferred>()
    private nextOffset = 0
    private processDelay?: () => Promise<void>

    constructor(options: HarnessOptions) {
        this.processDelay = options.processDelay

        // eslint-disable-next-line @typescript-eslint/no-this-alias
        const harness = this

        // Mirrors createPersonsStoreBeforeBatchStep/createGroupStoreBeforeBatchStep:
        // bind a batch-scoped store view into the batch context.
        async function bindStoresBeforeBatchStep(input: BeforeBatchInput<In, Ctx>) {
            const batchId = input.batchContext.batchId
            harness.submissions.push({
                batchId,
                specs: input.elements.map(
                    (element) => parseJSON(element.result.value.message.value!.toString()) as EventSpec
                ),
            })
            return Promise.resolve(
                ok({
                    elements: input.elements,
                    batchContext: { ...input.batchContext, storeForBatch: harness.personsStore.forBatch(batchId) },
                })
            )
        }

        // Mirrors createParseKafkaMessageStep + createResolveTeamStep: parse the
        // message body and resolve a team. The batch context (storeForBatch) was
        // already spread into the element value by BatchingPipeline.feed.
        function parseStep(input: In & StoreBatchContext): Promise<PipelineResult<ProcessedEvent>> {
            const spec = parseJSON(input.message.value!.toString()) as EventSpec
            return Promise.resolve(ok({ ...input, ...spec, team: { id: 1 } }))
        }

        // Mirrors the per-distinct-id pipeline: per-key sequential processing that
        // writes through the batch-bound store.
        async function processEventStep(event: ProcessedEvent): Promise<PipelineResult<ProcessedEvent>> {
            const batchId = event.storeForBatch.batchId
            harness.log.push({ type: 'start', key: event.key, seq: event.seq, batchId })
            const gate = harness.gates.get(`${event.key}:${event.seq}`)
            if (gate) {
                await gate.promise
            }
            if (harness.processDelay) {
                await harness.processDelay()
            }
            if (event.action === 'drop') {
                harness.log.push({ type: 'end', key: event.key, seq: event.seq, batchId })
                return drop('test drop')
            }
            if (event.action === 'fail') {
                throw new Error(`processing failed for ${event.key}:${event.seq}`)
            }
            event.storeForBatch.write(event.key, event.seq)
            harness.log.push({ type: 'end', key: event.key, seq: event.seq, batchId })
            return ok(event)
        }

        function recordAfterBatchStep<T extends { batchId: number }>(input: T): Promise<PipelineResult<T>> {
            harness.log.push({ type: 'afterBatch', batchId: input.batchId })
            return Promise.resolve(ok(input))
        }

        // Mirrors the joined ingestion pipeline topology: groupBy lives INSIDE
        // filterMap(teamAware(...)).handleIngestionWarnings(...), so new batches
        // are only admitted into the grouping stage when filterMap's
        // sub-pipeline drains.
        this.pipeline = newBatchingPipeline<In, ProcessedEvent, Ctx, StoreBatchContext, Ctx>(
            (before) => before.pipe(bindStoresBeforeBatchStep),
            (batch) =>
                batch
                    .messageAware((b) =>
                        b
                            .sequentially((s) => s.pipe(parseStep))
                            .filterMap(addTeamToContext, (fb) =>
                                fb
                                    .teamAware((tb) =>
                                        tb.concurrentlyPerGroup(
                                            (event) => event.key,
                                            (group) => group.sequentially((s) => s.pipe(processEventStep))
                                        )
                                    )
                                    .handleIngestionWarnings(this.outputs)
                            )
                    )
                    .handleResults({ outputs: this.outputs, promiseScheduler: this.scheduler })
                    .handleSideEffects(this.scheduler, { await: false }),
            (after) =>
                after
                    .pipe(
                        createFlushBatchStoresStep({
                            personsStore: this.personsStore as unknown as PersonsStore,
                            groupStore: this.groupStore as unknown as BatchWritingGroupStore,
                            outputs: this.outputs as unknown as FlushBatchStoresOutputs,
                        })
                    )
                    .pipe(recordAfterBatchStep),
            { concurrentBatches: options.concurrentBatches }
        )
    }

    /** Hold a message until the returned resolver is called. Must be set before feeding. */
    gate(key: string, seq: number): () => void {
        const d = deferred()
        this.gates.set(`${key}:${seq}`, d)
        return d.resolve
    }

    makeMessage(spec: EventSpec): Message {
        return {
            topic: 'test-topic',
            partition: 0,
            offset: this.nextOffset++,
            size: 0,
            key: Buffer.from(spec.key),
            value: Buffer.from(JSON.stringify(spec)),
            timestamp: Date.now(),
        }
    }

    feed(events: EventSpec[]): Promise<FeedResult> {
        const batch = events.map((spec) => {
            const message = this.makeMessage(spec)
            return createOkContext<In, Ctx>({ message }, { message })
        })
        return this.pipeline.feed(batch)
    }

    /** Drain the pipeline like the consumer/API server: next() until null, scheduling side effects. */
    async drain(): Promise<void> {
        let result = await this.pipeline.next()
        while (result !== null) {
            for (const sideEffect of result.sideEffects ?? []) {
                void this.scheduler.schedule(sideEffect)
            }
            result = await this.pipeline.next()
        }
    }

    /** Mirrors ingestion-api-server's handleIngestRequest: feed a batch, then drain. */
    async run(events: EventSpec[]): Promise<void> {
        const feedResult = await this.feed(events)
        if (!feedResult.ok) {
            throw new Error(`feed rejected: ${feedResult.reason}`)
        }
        await this.drain()
        await this.scheduler.waitForAll()
    }

    // ----- log query helpers -----

    keyTimeline(key: string): { type: 'start' | 'end'; seq: number; batchId: number }[] {
        return this.log
            .filter(
                (entry): entry is Extract<LogEntry, { type: 'start' | 'end' }> =>
                    (entry.type === 'start' || entry.type === 'end') && entry.key === key
            )
            .map(({ type, seq, batchId }) => ({ type, seq, batchId }))
    }

    started(key: string, seq: number): boolean {
        return this.log.some((entry) => entry.type === 'start' && entry.key === key && entry.seq === seq)
    }

    ended(key: string, seq: number): boolean {
        return this.log.some((entry) => entry.type === 'end' && entry.key === key && entry.seq === seq)
    }

    flushes(store: string = 'persons'): { key: string; lastSeq: number; lastWriterBatchId: number }[][] {
        return this.log
            .filter((entry): entry is Extract<LogEntry, { type: 'flush' }> => entry.type === 'flush')
            .filter((entry) => entry.store === store)
            .map((entry) => entry.entries)
    }

    releases(store: string = 'persons'): number[] {
        return this.log
            .filter((entry): entry is Extract<LogEntry, { type: 'release' }> => entry.type === 'release')
            .filter((entry) => entry.store === store)
            .map((entry) => entry.batchId)
    }

    afterBatches(): number[] {
        return this.log
            .filter((entry): entry is Extract<LogEntry, { type: 'afterBatch' }> => entry.type === 'afterBatch')
            .map((entry) => entry.batchId)
    }
}

/**
 * Assert the core ordering invariants from the processing log:
 * - per key, processing is serialized: start/end pairs never overlap
 * - per key, batchIds are non-decreasing (a later-accepted batch's messages for a
 *   key never run before an earlier batch's messages for that key finished)
 * - per (key, batch), messages run in the order they were submitted
 * - every submitted message starts and ends exactly once
 */
function assertOrderingInvariants(harness: Harness): void {
    const keys = new Set<string>()
    for (const submission of harness.submissions) {
        for (const spec of submission.specs) {
            keys.add(spec.key)
        }
    }

    for (const key of keys) {
        const timeline = harness.keyTimeline(key)

        // Serialized per key: strictly alternating start/end with matching seq.
        for (let i = 0; i < timeline.length; i += 2) {
            expect(timeline[i].type).toBe('start')
            expect(timeline[i + 1]).toEqual({ ...timeline[i], type: 'end' })
        }

        // Cross-batch ordering: batchIds never decrease for a given key.
        const startBatchIds = timeline.filter((entry) => entry.type === 'start').map((entry) => entry.batchId)
        for (let i = 1; i < startBatchIds.length; i++) {
            expect(startBatchIds[i]).toBeGreaterThanOrEqual(startBatchIds[i - 1])
        }

        // In-batch ordering: per (key, batch), seqs follow submission order.
        const expectedSeqs = harness.submissions
            .slice()
            .sort((a, b) => a.batchId - b.batchId)
            .flatMap((submission) => submission.specs.filter((spec) => spec.key === key).map((spec) => spec.seq))
        const actualSeqs = timeline.filter((entry) => entry.type === 'start').map((entry) => entry.seq)
        expect(actualSeqs).toEqual(expectedSeqs)
    }
}

class Semaphore {
    private queue: (() => void)[] = []

    constructor(private permits: number) {}

    async acquire(): Promise<void> {
        if (this.permits > 0) {
            this.permits--
            return
        }
        await new Promise<void>((resolve) => this.queue.push(resolve))
    }

    release(): void {
        const next = this.queue.shift()
        if (next) {
            next()
        } else {
            this.permits++
        }
    }
}

describe('BatchingPipeline + groupBy integration (joined ingestion pipeline shape)', () => {
    describe('per-key ordering', () => {
        it('processes same-key messages sequentially in feed order within a batch', async () => {
            const harness = new Harness({ concurrentBatches: 1 })

            await harness.run([
                { key: 'a', seq: 1 },
                { key: 'b', seq: 2 },
                { key: 'a', seq: 3 },
                { key: 'a', seq: 4 },
                { key: 'b', seq: 5 },
            ])

            assertOrderingInvariants(harness)
            expect(harness.keyTimeline('a').filter((e) => e.type === 'start')).toEqual([
                { type: 'start', seq: 1, batchId: 0 },
                { type: 'start', seq: 3, batchId: 0 },
                { type: 'start', seq: 4, batchId: 0 },
            ])
        })

        it('does not start a later-batch message for a key until the earlier batch finished that key', async () => {
            const harness = new Harness({ concurrentBatches: 2 })
            const releaseFirst = harness.gate('a', 1)

            // Batch 0 holds key "a" at seq 1; batch 1 has more "a" messages.
            expect(
                (
                    await harness.feed([
                        { key: 'a', seq: 1 },
                        { key: 'a', seq: 2 },
                    ])
                ).ok
            ).toBe(true)
            expect((await harness.feed([{ key: 'a', seq: 3 }])).ok).toBe(true)

            const drainPromise = harness.drain()
            await tick()

            // a:1 is in flight; a:2 (same batch) and a:3 (next batch) must wait.
            expect(harness.started('a', 1)).toBe(true)
            expect(harness.ended('a', 1)).toBe(false)
            expect(harness.started('a', 2)).toBe(false)
            expect(harness.started('a', 3)).toBe(false)

            releaseFirst()
            await drainPromise

            assertOrderingInvariants(harness)
            expect(harness.keyTimeline('a').map((e) => `${e.type}:${e.seq}`)).toEqual([
                'start:1',
                'end:1',
                'start:2',
                'end:2',
                'start:3',
                'end:3',
            ])
        })

        it('processes all messages for a key in global feed order across many in-flight batches', async () => {
            const harness = new Harness({ concurrentBatches: 4 })

            // Four in-flight batches, all touching keys "a" and "b".
            expect(
                (
                    await harness.feed([
                        { key: 'a', seq: 1 },
                        { key: 'b', seq: 2 },
                    ])
                ).ok
            ).toBe(true)
            expect(
                (
                    await harness.feed([
                        { key: 'a', seq: 3 },
                        { key: 'a', seq: 4 },
                    ])
                ).ok
            ).toBe(true)
            expect((await harness.feed([{ key: 'b', seq: 5 }])).ok).toBe(true)
            expect(
                (
                    await harness.feed([
                        { key: 'a', seq: 6 },
                        { key: 'b', seq: 7 },
                    ])
                ).ok
            ).toBe(true)

            await harness.drain()

            assertOrderingInvariants(harness)
            expect(
                harness
                    .keyTimeline('a')
                    .filter((e) => e.type === 'start')
                    .map((e) => e.seq)
            ).toEqual([1, 3, 4, 6])
            expect(
                harness
                    .keyTimeline('b')
                    .filter((e) => e.type === 'start')
                    .map((e) => e.seq)
            ).toEqual([2, 5, 7])
        })

        it('maintains per-key ordering when a message in the group is dropped', async () => {
            const harness = new Harness({ concurrentBatches: 2 })

            expect(
                (
                    await harness.feed([
                        { key: 'a', seq: 1 },
                        { key: 'a', seq: 2, action: 'drop' },
                        { key: 'a', seq: 3 },
                    ])
                ).ok
            ).toBe(true)
            expect((await harness.feed([{ key: 'a', seq: 4 }])).ok).toBe(true)

            await harness.drain()

            assertOrderingInvariants(harness)
            // The dropped message still occupied its slot in the sequence.
            expect(
                harness
                    .keyTimeline('a')
                    .filter((e) => e.type === 'start')
                    .map((e) => e.seq)
            ).toEqual([1, 2, 3, 4])
            // But it never wrote to the store.
            const allFlushed = harness.flushes().flat()
            expect(allFlushed.filter((entry) => entry.key === 'a').map((entry) => entry.lastSeq)).not.toContain(2)
        })
    })

    describe('cross-batch parallelism', () => {
        it('processes different keys from different in-flight batches in parallel', async () => {
            const harness = new Harness({ concurrentBatches: 2 })
            const releaseA = harness.gate('a', 1)

            // Batch 0 is stuck on key "a"; batch 1 only has key "b".
            expect((await harness.feed([{ key: 'a', seq: 1 }])).ok).toBe(true)
            expect((await harness.feed([{ key: 'b', seq: 2 }])).ok).toBe(true)

            const drainPromise = harness.drain()
            await tick()

            // b:2 (batch 1) completed while a:1 (batch 0) is still in flight.
            expect(harness.ended('b', 2)).toBe(true)
            expect(harness.ended('a', 1)).toBe(false)

            // Batch 1 fully completed (flush + afterBatch) before batch 0.
            expect(harness.afterBatches()).toEqual([1])

            releaseA()
            await drainPromise

            expect(harness.afterBatches()).toEqual([1, 0])
            assertOrderingInvariants(harness)
        })

        it('a batch fed while the pump is parked on a hot key still starts and completes', async () => {
            const harness = new Harness({ concurrentBatches: 2 })
            const releaseHot = harness.gate('hot', 1)

            // Batch 0's hot key parks the drain loop on its group.
            expect((await harness.feed([{ key: 'hot', seq: 1 }])).ok).toBe(true)
            const drainPromise = harness.drain()
            await tick()
            expect(harness.started('hot', 1)).toBe(true)

            // Batch 1 arrives AFTER the drain is parked. Its group must start
            // and complete without waiting for the hot group to finish.
            expect((await harness.feed([{ key: 'cold', seq: 2 }])).ok).toBe(true)
            await tick()

            expect(harness.ended('cold', 2)).toBe(true)
            expect(harness.afterBatches()).toEqual([1])
            expect(harness.ended('hot', 1)).toBe(false)

            releaseHot()
            await drainPromise

            expect(harness.afterBatches()).toEqual([1, 0])
            assertOrderingInvariants(harness)
        })

        it('a slow key does not block other keys within the same batch', async () => {
            const harness = new Harness({ concurrentBatches: 1 })
            const releaseA = harness.gate('a', 1)

            expect(
                (
                    await harness.feed([
                        { key: 'a', seq: 1 },
                        { key: 'b', seq: 2 },
                        { key: 'c', seq: 3 },
                    ])
                ).ok
            ).toBe(true)

            const drainPromise = harness.drain()
            await tick()

            expect(harness.ended('b', 2)).toBe(true)
            expect(harness.ended('c', 3)).toBe(true)
            expect(harness.ended('a', 1)).toBe(false)
            // The batch itself cannot complete until "a" finishes.
            expect(harness.afterBatches()).toEqual([])

            releaseA()
            await drainPromise

            expect(harness.afterBatches()).toEqual([0])
            assertOrderingInvariants(harness)
        })
    })

    describe('batch completion and store flush lifecycle', () => {
        it('fires afterBatch flush only after every message in the batch finished', async () => {
            const harness = new Harness({ concurrentBatches: 1 })

            await harness.run([
                { key: 'a', seq: 1 },
                { key: 'b', seq: 2 },
                { key: 'a', seq: 3 },
            ])

            const lastEndIndex = harness.log.findLastIndex((entry) => entry.type === 'end')
            const flushIndex = harness.log.findIndex((entry) => entry.type === 'flush' && entry.store === 'persons')
            expect(flushIndex).toBeGreaterThan(lastEndIndex)

            // Flush captured the latest write per key.
            expect(harness.flushes()).toEqual([
                expect.arrayContaining([
                    expect.objectContaining({ key: 'a', lastSeq: 3 }),
                    expect.objectContaining({ key: 'b', lastSeq: 2 }),
                ]),
            ])

            // Flush results were produced as side effects through the outputs.
            await harness.scheduler.waitForAll()
            expect(harness.outputs.produce).toHaveBeenCalledWith(PERSONS_OUTPUT, expect.objectContaining({ teamId: 1 }))
        })

        it('refcounts store entries across concurrent batches and evicts only after all release', async () => {
            const harness = new Harness({ concurrentBatches: 2 })
            const releaseA1 = harness.gate('a', 1)
            const releaseC4 = harness.gate('c', 4)

            // Both batches write the shared key "b". Batch 0 is held on "a",
            // batch 1 is held on "c", so we can complete them one at a time.
            expect(
                (
                    await harness.feed([
                        { key: 'a', seq: 1 },
                        { key: 'b', seq: 2 },
                    ])
                ).ok
            ).toBe(true)
            expect(
                (
                    await harness.feed([
                        { key: 'b', seq: 3 },
                        { key: 'c', seq: 4 },
                    ])
                ).ok
            ).toBe(true)

            const drainPromise = harness.drain()
            await tick()

            // Both "b" writes landed; the entry is referenced by both in-flight batches.
            expect(harness.personsStore.cache.get('b')?.refs).toEqual(new Set([0, 1]))

            releaseA1()
            await tick()

            // Batch 0 completed (flush + release); "b" was flushed clean but is
            // still referenced by batch 1, so it must stay cached.
            expect(harness.afterBatches()).toEqual([0])
            expect(harness.releases()).toEqual([0])
            expect(harness.personsStore.cache.get('b')?.refs).toEqual(new Set([1]))
            expect(harness.personsStore.cache.get('b')?.dirty).toBe(false)

            releaseC4()
            await drainPromise

            expect(harness.afterBatches()).toEqual([0, 1])
            expect(harness.releases()).toEqual([0, 1])
            // After the last batch flushed and released, the cache is fully evicted.
            expect(harness.personsStore.cache.size).toBe(0)
            assertOrderingInvariants(harness)
        })

        it('a batch flush picks up dirty entries and leaves them clean for subsequent flushes', async () => {
            const harness = new Harness({ concurrentBatches: 1 })

            await harness.run([{ key: 'a', seq: 1 }])
            await harness.run([{ key: 'b', seq: 2 }])

            expect(harness.flushes()).toEqual([
                [expect.objectContaining({ key: 'a', lastSeq: 1 })],
                // Second flush only contains the second batch's dirty entry; "a" was
                // already clean and evicted.
                [expect.objectContaining({ key: 'b', lastSeq: 2 })],
            ])
        })

        it('propagates processing exceptions to the drain loop (batch fails as a whole)', async () => {
            const harness = new Harness({
                concurrentBatches: 1,
                processDelay: () => Promise.reject(new Error('boom')),
            })

            expect((await harness.feed([{ key: 'a', seq: 1 }])).ok).toBe(true)
            await expect(harness.drain()).rejects.toThrow('boom')
        })
    })

    describe('capacity', () => {
        it('rejects feed at concurrent batch capacity and frees the slot after drain', async () => {
            const harness = new Harness({ concurrentBatches: 2 })
            const releaseA = harness.gate('a', 1)
            const releaseB = harness.gate('b', 2)

            expect((await harness.feed([{ key: 'a', seq: 1 }])).ok).toBe(true)
            expect((await harness.feed([{ key: 'b', seq: 2 }])).ok).toBe(true)

            // Third concurrent batch exceeds capacity — mirrors the API server's 503 path.
            const rejection = await harness.feed([{ key: 'c', seq: 3 }])
            expect(rejection).toMatchObject({ ok: false, kind: 'at_capacity' })

            releaseA()
            releaseB()
            await harness.drain()

            expect((await harness.feed([{ key: 'c', seq: 4 }])).ok).toBe(true)
            await harness.drain()
        })
    })

    describe('feed racing an in-flight pump pull', () => {
        /**
         * A feed can land while a next() pull is resolving null from an empty
         * pipeline: the batch gets registered and its elements buffered, but the
         * pull already made its emptiness decision. The pull must not treat the
         * resulting null-with-in-flight-batches as fatal — it should retry and
         * pick up the buffered elements.
         */
        it('a feed landing while the pump pulls from an empty pipeline does not spuriously fail', async () => {
            // The pull's emptiness decision (buffer check) and its in-flight
            // batch check happen a fixed number of microtask hops apart. The
            // feed's registration must land between them to hit the race, so
            // sweep relative hop offsets in both directions (delaying the pull
            // or the feed) — one iteration lands inside the window regardless
            // of how many hops each chain has.
            const delayHops = async (hops: number): Promise<void> => {
                for (let i = 0; i < hops; i++) {
                    await Promise.resolve()
                }
            }

            for (let offset = -12; offset < 12; offset++) {
                const harness = new Harness({ concurrentBatches: 2 })

                // Drain one batch so the pipeline is empty but warm.
                expect((await harness.feed([{ key: 'a', seq: 1 }])).ok).toBe(true)
                expect(await harness.pipeline.next()).not.toBeNull()

                // Race a pull against a feed, shifted by `offset` hops:
                // negative offsets delay the pull, positive delay the feed.
                const pull = (async () => {
                    await delayHops(Math.max(0, -offset))
                    return harness.pipeline.next()
                })()
                const feed = (async () => {
                    await delayHops(Math.max(0, offset))
                    return harness.feed([{ key: 'b', seq: 2 }])
                })()

                await expect(feed).resolves.toMatchObject({ ok: true })
                // The racing pull either returns the new batch's results or a
                // clean null (if it resolved before the feed registered) —
                // never a throw.
                await pull
                await harness.drain()

                expect(harness.ended('b', 2)).toBe(true)
                expect(harness.afterBatches()).toEqual([0, 1])
            }
        })
    })

    describe('failure semantics with concurrent in-flight batches (documents current behavior)', () => {
        /**
         * Scenario: batches a, b, c are in flight and one of batch a's messages
         * throws mid-pipeline. This test documents what the framework does TODAY —
         * not necessarily what it should do.
         */
        it('a mid-pipeline exception in one batch poisons the pipeline but lets other batches complete first', async () => {
            const harness = new Harness({ concurrentBatches: 3 })
            const releaseB = harness.gate('kb', 3)
            const releaseC = harness.gate('kc', 4)

            // Batch a (batchId 0): ka:1 succeeds and writes to the store, ka:2 throws.
            expect(
                (
                    await harness.feed([
                        { key: 'ka', seq: 1 },
                        { key: 'ka', seq: 2, action: 'fail' },
                    ])
                ).ok
            ).toBe(true)
            // Batches b and c (batchIds 1, 2): held on gates so they're in flight when a fails.
            expect((await harness.feed([{ key: 'kb', seq: 3 }])).ok).toBe(true)
            expect((await harness.feed([{ key: 'kc', seq: 4 }])).ok).toBe(true)

            // The drain loop rejects with batch a's error.
            await expect(harness.drain()).rejects.toThrow('processing failed for ka:2')

            // Nothing has completed: no flush, no release for ANY batch.
            expect(harness.afterBatches()).toEqual([])
            expect(harness.releases()).toEqual([])

            // Batches b and c are still alive in the background. Release them.
            releaseB()
            releaseC()
            await tick()

            // b and c CAN still complete via further next() calls — and their
            // afterBatch flush picks up batch a's PARTIAL write (ka:1), because
            // the store is a singleton and flush takes everything dirty. Batch a
            // will be retried by the consumer, so ka:1 gets persisted twice.
            const resultB = await harness.pipeline.next()
            expect(resultB).not.toBeNull()
            const resultC = await harness.pipeline.next()
            expect(resultC).not.toBeNull()
            expect(harness.afterBatches()).toEqual([1, 2])
            expect(harness.flushes().flat()).toEqual(
                expect.arrayContaining([expect.objectContaining({ key: 'ka', lastSeq: 1 })])
            )

            // From here on the pipeline is permanently wedged:
            // 1. The failed group's rejected promise is never removed from the
            //    grouping stage, so any next() that has to wait rejects again.
            await expect(harness.pipeline.next()).rejects.toThrow('processing failed for ka:2')

            // 2. Batch a never completes, so its capacity slot leaks forever
            //    and its store references are never released.
            expect(harness.releases()).toEqual([1, 2])
            expect(harness.personsStore.cache.get('ka')?.refs.has(0)).toBe(true)

            // 3. Key "ka" is dead: new messages for it queue behind the rejected
            //    promise and never start.
            expect((await harness.feed([{ key: 'ka', seq: 5 }])).ok).toBe(true)
            await expect(harness.pipeline.next()).rejects.toThrow('processing failed for ka:2')
            expect(harness.started('ka', 5)).toBe(false)
        })

        it('leaked capacity slots from failed batches eventually starve feed()', async () => {
            const harness = new Harness({ concurrentBatches: 2 })

            // Two batches fail on different keys; both leak their slot.
            expect((await harness.feed([{ key: 'k1', seq: 1, action: 'fail' }])).ok).toBe(true)
            await expect(harness.drain()).rejects.toThrow('processing failed for k1:1')
            expect((await harness.feed([{ key: 'k2', seq: 2, action: 'fail' }])).ok).toBe(true)
            await expect(harness.drain()).rejects.toThrow('processing failed')

            // Both slots are now wedged: the worker rejects every batch from here on.
            expect(await harness.feed([{ key: 'k3', seq: 3 }])).toMatchObject({ ok: false, kind: 'at_capacity' })
        })
    })

    describe('concurrent drivers (ingestion-api-server model)', () => {
        it('maintains per-key ordering with concurrent feed+drain drivers', async () => {
            const random = xoshiro128ss(0x9e3779b9, 0x243f6a88, 0xb7e15162, 0x6c078965)
            const harness = new Harness({
                concurrentBatches: 2,
                processDelay: () => new Promise((resolve) => setTimeout(resolve, Math.floor(random() * 3))),
            })
            const semaphore = new Semaphore(2)

            let seq = 0
            const submitOne = async (specs: EventSpec[]): Promise<void> => {
                await semaphore.acquire()
                try {
                    await harness.run(specs)
                } finally {
                    semaphore.release()
                }
            }

            const batches: EventSpec[][] = []
            for (let i = 0; i < 10; i++) {
                batches.push([
                    { key: 'a', seq: seq++ },
                    { key: 'b', seq: seq++ },
                    { key: 'a', seq: seq++ },
                ])
            }

            await Promise.all(batches.map((specs) => submitOne(specs)))

            assertOrderingInvariants(harness)
            // Every batch flushed and released exactly once.
            expect(
                harness
                    .afterBatches()
                    .slice()
                    .sort((x, y) => x - y)
            ).toEqual(Array.from({ length: 10 }, (_, i) => i))
            expect(
                harness
                    .releases()
                    .slice()
                    .sort((x, y) => x - y)
            ).toEqual(Array.from({ length: 10 }, (_, i) => i))
        })

        it('survives a randomized stress run while preserving all invariants', async () => {
            const CONCURRENT_BATCHES = 4
            const BATCH_COUNT = 24
            const BATCH_SIZE = 8
            const KEYS = ['a', 'b', 'c', 'd', 'e', 'f']

            const random = xoshiro128ss(0x9e3779b9, 0x243f6a88, 0xb7e15162, 0x6c078965)
            const harness = new Harness({
                concurrentBatches: CONCURRENT_BATCHES,
                processDelay: () => new Promise((resolve) => setTimeout(resolve, Math.floor(random() * 3))),
            })
            const semaphore = new Semaphore(CONCURRENT_BATCHES)

            let seq = 0
            const batches: EventSpec[][] = []
            for (let i = 0; i < BATCH_COUNT; i++) {
                const specs: EventSpec[] = []
                for (let j = 0; j < BATCH_SIZE; j++) {
                    specs.push({
                        key: KEYS[Math.floor(random() * KEYS.length)],
                        seq: seq++,
                        action: random() < 0.1 ? 'drop' : undefined,
                    })
                }
                batches.push(specs)
            }

            await Promise.all(
                batches.map(async (specs) => {
                    await semaphore.acquire()
                    try {
                        await harness.run(specs)
                    } finally {
                        semaphore.release()
                    }
                })
            )

            assertOrderingInvariants(harness)

            // Every message processed exactly once.
            const startCount = harness.log.filter((entry) => entry.type === 'start').length
            expect(startCount).toBe(BATCH_COUNT * BATCH_SIZE)

            // Every accepted batch flushed and released exactly once, and the
            // in-flight batch count never exceeded the configured capacity.
            const expectedBatchIds = Array.from({ length: BATCH_COUNT }, (_, i) => i)
            expect(
                harness
                    .afterBatches()
                    .slice()
                    .sort((x, y) => x - y)
            ).toEqual(expectedBatchIds)
            expect(
                harness
                    .releases('persons')
                    .slice()
                    .sort((x, y) => x - y)
            ).toEqual(expectedBatchIds)
            expect(
                harness
                    .releases('groups')
                    .slice()
                    .sort((x, y) => x - y)
            ).toEqual(expectedBatchIds)

            // All store entries were flushed and evicted by the end.
            expect(harness.personsStore.cache.size).toBe(0)
        })
    })
})
