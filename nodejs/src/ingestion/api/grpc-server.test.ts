import { create } from '@bufbuild/protobuf'
import { Code, ConnectError } from '@connectrpc/connect'
import { register } from 'prom-client'

import {
    IngestStreamRequest,
    IngestStreamRequestSchema,
    IngestStreamResponse,
    KafkaMessageSchema,
    StreamHelloSchema,
    SubBatchAck,
    SubBatchStatus,
} from '~/common/generated/ingestion-worker/ingestion/worker/v1/worker_pb'
import { FeedResult } from '~/ingestion/framework/batching-pipeline'

import { FeedOrderSentinel } from './feed-order-sentinel'
import { CompletedSubBatch, StreamIngestDriver, WorkerIngestServer } from './grpc-server'

class Deferred<T> {
    resolve!: (value: T) => void
    reject!: (error: Error) => void
    promise = new Promise<T>((resolve, reject) => {
        this.resolve = resolve
        this.reject = reject
    })
}

/** Push-based request source standing in for the consumer's side of the stream. */
class FrameSource implements AsyncIterable<IngestStreamRequest> {
    private frames: IngestStreamRequest[] = []
    private waiters: Deferred<IteratorResult<IngestStreamRequest>>[] = []
    private done = false

    push(frame: IngestStreamRequest): void {
        const waiter = this.waiters.shift()
        if (waiter) {
            waiter.resolve({ value: frame, done: false })
            return
        }
        this.frames.push(frame)
    }

    end(): void {
        this.done = true
        for (const waiter of this.waiters.splice(0)) {
            waiter.resolve({ value: undefined, done: true })
        }
    }

    [Symbol.asyncIterator](): AsyncIterator<IngestStreamRequest> {
        return {
            next: (): Promise<IteratorResult<IngestStreamRequest>> => {
                if (this.frames.length > 0) {
                    return Promise.resolve({ value: this.frames.shift()!, done: false })
                }
                if (this.done) {
                    return Promise.resolve({ value: undefined, done: true })
                }
                const waiter = new Deferred<IteratorResult<IngestStreamRequest>>()
                this.waiters.push(waiter)
                return waiter.promise
            },
        }
    }
}

/** Records feeds and lets the test hand-complete batches. */
class FakeDriver implements StreamIngestDriver {
    feeds: { streamId: number; seq: number; offsets: number[] }[] = []
    feedResult: FeedResult = { ok: true }
    private completions: CompletedSubBatch[] = []
    private nextWaiters: Deferred<CompletedSubBatch | null>[] = []
    nextError: Error | null = null

    feed(streamId: number, seq: number, messages: { offset: number }[]): Promise<FeedResult> {
        this.feeds.push({ streamId, seq, offsets: messages.map((m) => m.offset) })
        return Promise.resolve(this.feedResult)
    }

    next(): Promise<CompletedSubBatch | null> {
        if (this.nextError) {
            return Promise.reject(this.nextError)
        }
        if (this.completions.length > 0) {
            return Promise.resolve(this.completions.shift()!)
        }
        const waiter = new Deferred<CompletedSubBatch | null>()
        this.nextWaiters.push(waiter)
        return waiter.promise
    }

    complete(batch: Omit<CompletedSubBatch, 'settled'>, settled: Promise<void> = Promise.resolve()): void {
        const completed: CompletedSubBatch = { ...batch, settled }
        const waiter = this.nextWaiters.shift()
        if (waiter) {
            waiter.resolve(completed)
            return
        }
        this.completions.push(completed)
    }

    failNext(error: Error): void {
        this.nextError = error
        const waiter = this.nextWaiters.shift()
        if (waiter) {
            waiter.reject(error)
        }
    }
}

function hello(overrides: { consumerId?: string; streamEpoch?: bigint } = {}): IngestStreamRequest {
    return create(IngestStreamRequestSchema, {
        msg: {
            case: 'hello',
            value: create(StreamHelloSchema, {
                consumerId: overrides.consumerId ?? 'consumer-1',
                streamEpoch: overrides.streamEpoch ?? 1n,
            }),
        },
    })
}

function subBatch(
    seq: number,
    offsets: number[],
    overrides: { replay?: boolean; assignmentEpoch?: bigint } = {}
): IngestStreamRequest {
    return create(IngestStreamRequestSchema, {
        msg: {
            case: 'subBatch',
            value: {
                seq: BigInt(seq),
                batchId: `batch-${seq}`,
                replay: overrides.replay ?? false,
                assignmentEpoch: overrides.assignmentEpoch ?? 1n,
                messages: offsets.map((offset) =>
                    create(KafkaMessageSchema, {
                        topic: 'events',
                        partition: 0,
                        offset: BigInt(offset),
                        timestamp: 0n,
                        key: 'k',
                        value: '{}',
                        headers: { token: 'tok', distinct_id: 'd1' },
                    })
                ),
            },
        },
    })
}

interface Collected {
    /** Sub-batch acks, unwrapped from the response oneof. */
    acks: SubBatchAck[]
    /** Every response frame in arrival order, ready frame included. */
    all: IngestStreamResponse[]
    error: ConnectError | null
    ended: Promise<void>
}

function collect(server: WorkerIngestServer, source: FrameSource, signal?: AbortSignal): Collected {
    const collected: Collected = { acks: [], all: [], error: null, ended: Promise.resolve() }
    collected.ended = (async () => {
        try {
            for await (const frame of server.ingestStream(source, signal)) {
                collected.all.push(frame)
                if (frame.msg.case === 'ack') {
                    collected.acks.push(frame.msg.value)
                }
            }
        } catch (error) {
            collected.error = error as ConnectError
        }
    })()
    return collected
}

async function until(condition: () => boolean | Promise<boolean>): Promise<void> {
    const deadline = Date.now() + 5_000
    while (!(await condition())) {
        if (Date.now() > deadline) {
            throw new Error('condition not met within 5s')
        }
        await new Promise((resolve) => setTimeout(resolve, 2))
    }
}

async function outOfOrderCount(): Promise<number> {
    const metric = register.getSingleMetric('ingestion_api_out_of_order_messages_total')
    const value = (await metric!.get()).values[0]?.value
    return value ?? 0
}

async function slotWaiters(): Promise<number> {
    const metric = register.getSingleMetric('ingestion_api_grpc_feed_slot_waiters')
    const value = (await metric!.get()).values[0]?.value
    return value ?? 0
}

async function metricValue(name: string): Promise<number> {
    const metric = register.getSingleMetric(name)
    const value = (await metric!.get()).values[0]?.value
    return value ?? 0
}

describe('WorkerIngestServer', () => {
    let server: WorkerIngestServer
    let driver: FakeDriver
    let onFatal: jest.Mock
    let sentinel: FeedOrderSentinel

    beforeEach(async () => {
        driver = new FakeDriver()
        onFatal = jest.fn()
        sentinel = new FeedOrderSentinel()
        server = new WorkerIngestServer(
            { port: 0, maxConcurrentBatches: 4, capacityRetryMs: 1, pumpIdleMs: 1, drainTimeoutMs: 200 },
            { driver, feedOrderSentinel: sentinel, onFatal }
        )
        await server.start()
    })

    afterEach(async () => {
        await server.stop()
    })

    it('sends a ready frame before any work arrives', async () => {
        // Regression: connect-node flushes response headers only with the
        // first response message, and the consumer's stream-open awaits those
        // headers before sending anything — without an immediate ready frame
        // the two sides deadlock at open (observed against production workers).
        const source = new FrameSource()
        const collected = collect(server, source)

        source.push(hello())
        await until(() => collected.all.length === 1)
        expect(collected.all[0].msg.case).toBe('ready')
        source.end()
        await collected.ended
        expect(collected.error).toBeNull()
    })

    it('acks completions out of order by seq and ends the stream after half-close', async () => {
        const source = new FrameSource()
        const collected = collect(server, source)

        source.push(hello())
        source.push(subBatch(1, [10, 11]))
        source.push(subBatch(2, [12]))
        await until(() => driver.feeds.length === 2)
        const streamId = driver.feeds[0].streamId

        // Sub-batch 2 finishes first — its ack must not wait for sub-batch 1.
        driver.complete({ streamId, seq: 2, accepted: 1 })
        await until(() => collected.acks.length === 1)
        driver.complete({ streamId, seq: 1, accepted: 2 })
        source.end()
        await collected.ended

        expect(collected.error).toBeNull()
        expect(collected.acks.map((ack) => [Number(ack.seq), ack.status, ack.accepted])).toEqual([
            [2, SubBatchStatus.OK, 1],
            [1, SubBatchStatus.OK, 2],
        ])
        expect(server.streamCount).toBe(0)
    })

    it('stop() drains in-flight sub-batch acks before ending streams', async () => {
        const source = new FrameSource()
        const collected = collect(server, source)

        source.push(hello())
        source.push(subBatch(1, [10]))
        await until(() => driver.feeds.length === 1)
        const streamId = driver.feeds[0].streamId

        // The batch settles only after stop() has begun — its ack must still
        // reach the consumer, or every scale-down forces a replay.
        const stopping = server.stop()

        // A stream opened mid-drain must be refused, not fed.
        const late = collect(server, new FrameSource())
        await late.ended
        expect(late.error?.code).toBe(Code.Unavailable)

        driver.complete({ streamId, seq: 1, accepted: 1 })
        await stopping
        source.end()
        await collected.ended

        expect(collected.error).toBeNull()
        expect(collected.acks.map((ack) => [Number(ack.seq), ack.accepted])).toEqual([[1, 1]])
        expect(driver.feeds).toHaveLength(1)
    })

    it('feeds sub-batches in stream order, stalling reads while the pipeline is at capacity', async () => {
        const source = new FrameSource()
        collect(server, source)

        driver.feedResult = { ok: false, kind: 'at_capacity', reason: 'full' }
        source.push(hello())
        source.push(subBatch(1, [10]))
        source.push(subBatch(2, [11]))

        // Sub-batch 1 keeps retrying; sub-batch 2 must not reach the driver.
        await until(() => driver.feeds.length >= 2)
        expect(driver.feeds.every((feed) => feed.seq === 1)).toBe(true)

        driver.feedResult = { ok: true }
        await until(() => driver.feeds.some((feed) => feed.seq === 2))
        const acceptedOrder = driver.feeds.filter((feed, i) => driver.feeds.findIndex((f) => f.seq === feed.seq) === i)
        expect(acceptedOrder.map((feed) => feed.seq)).toEqual([1, 2])
    })

    it.each([
        ['a sub-batch before the hello', [subBatch(1, [10])]],
        ['a duplicate hello', [hello(), hello()]],
        ['a seq gap', [hello(), subBatch(2, [10])]],
    ])('closes the stream on %s without feeding the offending frame', async (_name, frames) => {
        const source = new FrameSource()
        const collected = collect(server, source)

        for (const frame of frames) {
            source.push(frame)
        }
        await collected.ended

        expect(collected.error).not.toBeNull()
        expect(collected.error!.code).toBe(Code.FailedPrecondition)
        expect(driver.feeds).toEqual([])
        expect(server.streamCount).toBe(0)
    })

    it('acks an empty sub-batch immediately instead of feeding it', async () => {
        // An empty feed() is a no-op that never completes a batch — feeding it
        // would leave the consumer waiting for an ack forever.
        const source = new FrameSource()
        const collected = collect(server, source)

        source.push(hello())
        source.push(subBatch(1, []))
        await until(() => collected.acks.length === 1)
        source.end()
        await collected.ended

        expect(collected.error).toBeNull()
        expect(collected.acks[0].accepted).toBe(0)
        expect(driver.feeds).toEqual([])
    })

    it('fails the stream and reports fatal when the pipeline dies mid-batch', async () => {
        const source = new FrameSource()
        const collected = collect(server, source)

        source.push(hello())
        source.push(subBatch(1, [10]))
        await until(() => driver.feeds.length === 1)
        driver.failNext(new Error('pipeline poisoned'))
        await collected.ended

        expect(collected.error!.code).toBe(Code.Internal)
        expect(onFatal).toHaveBeenCalledWith(expect.objectContaining({ message: 'pipeline poisoned' }))
    })

    it('nacks a rejected sub-batch before closing the stream', async () => {
        const source = new FrameSource()
        const collected = collect(server, source)

        driver.feedResult = { ok: false, kind: 'before_batch_failed', reason: 'hook failed' }
        source.push(hello())
        source.push(subBatch(1, [10]))
        await collected.ended

        expect(collected.acks.map((ack) => [Number(ack.seq), ack.status])).toEqual([[1, SubBatchStatus.FAILED]])
        expect(collected.acks[0].error).toBe('hook failed')
        expect(collected.error!.code).toBe(Code.Internal)
    })

    it('grants feed slots in arrival order across streams instead of racing', async () => {
        // Regression: capacity was granted by a retry race, so a busy stream
        // could starve a quiet one indefinitely — in prod, consumers wedged
        // with zero completed batches while their sub-batches sat unfed.
        const fairDriver = new FakeDriver()
        const fairServer = new WorkerIngestServer(
            { port: 0, maxConcurrentBatches: 1, capacityRetryMs: 1, pumpIdleMs: 1, drainTimeoutMs: 50 },
            { driver: fairDriver, onFatal: jest.fn() }
        )
        await fairServer.start()
        try {
            const sourceA = new FrameSource()
            const sourceB = new FrameSource()
            collect(fairServer, sourceA)
            collect(fairServer, sourceB)
            sourceA.push(hello({ consumerId: 'consumer-a' }))
            sourceB.push(hello({ consumerId: 'consumer-b' }))

            // A1 takes the only slot; A2 then queues for it.
            sourceA.push(subBatch(1, [1]))
            await until(() => fairDriver.feeds.length === 1)
            const streamA = fairDriver.feeds[0].streamId
            sourceA.push(subBatch(2, [2]))
            await until(async () => (await slotWaiters()) === 1)
            // B1 arrives third, A3 fourth.
            sourceB.push(subBatch(1, [3]))
            await until(async () => (await slotWaiters()) === 2)
            sourceA.push(subBatch(3, [4]))

            fairDriver.complete({ streamId: streamA, seq: 1, accepted: 1 })
            await until(() => fairDriver.feeds.length === 2)
            fairDriver.complete({ streamId: streamA, seq: 2, accepted: 1 })
            // B1 must get the freed slot before A3 — arrival order, not race.
            await until(() => fairDriver.feeds.length === 3)
            expect(fairDriver.feeds[2].streamId).not.toBe(streamA)
        } finally {
            await fairServer.stop()
        }
    })

    it('drops a cancelled stream from the admission queue so its slot skips to a live stream', async () => {
        // Regression: a stream that disconnected while waiting for a slot left
        // its waiter in the FIFO queue. A freed slot was granted to that dead
        // waiter ahead of live streams, feeding work that could never be acked
        // and starving real traffic under repeated disconnects.
        const laneDriver = new FakeDriver()
        const laneServer = new WorkerIngestServer(
            { port: 0, maxConcurrentBatches: 1, capacityRetryMs: 1, pumpIdleMs: 1, drainTimeoutMs: 50 },
            { driver: laneDriver, onFatal: jest.fn() }
        )
        await laneServer.start()
        try {
            const sourceA = new FrameSource()
            const cancelled = new AbortController()
            const sourceCancelled = new FrameSource()
            const sourceLive = new FrameSource()
            collect(laneServer, sourceA)
            collect(laneServer, sourceCancelled, cancelled.signal)
            collect(laneServer, sourceLive)

            sourceA.push(hello({ consumerId: 'consumer-a' }))
            sourceCancelled.push(hello({ consumerId: 'consumer-cancelled' }))
            sourceLive.push(hello({ consumerId: 'consumer-live' }))

            // A takes the only slot; the soon-to-cancel stream queues behind it.
            // The waiter gauge is process-global, so track it against a baseline.
            sourceA.push(subBatch(1, [1]))
            await until(() => laneDriver.feeds.length === 1)
            const streamA = laneDriver.feeds[0].streamId
            const baseWaiters = await slotWaiters()
            sourceCancelled.push(subBatch(1, [2]))
            await until(async () => (await slotWaiters()) === baseWaiters + 1)

            // The stream disconnects while parked — its waiter must leave the queue.
            cancelled.abort()
            await until(async () => (await slotWaiters()) === baseWaiters)

            // A live stream queues, then A's slot frees: it must go to the live
            // stream, and the cancelled stream's sub-batch (offset 2) never feeds.
            sourceLive.push(subBatch(1, [3]))
            await until(async () => (await slotWaiters()) === baseWaiters + 1)
            laneDriver.complete({ streamId: streamA, seq: 1, accepted: 1 })
            await until(() => laneDriver.feeds.length === 2)

            expect(laneDriver.feeds[1].offsets).toEqual([3])
            expect(laneDriver.feeds.some((f) => f.offsets.includes(2))).toBe(false)
        } finally {
            await laneServer.stop()
        }
    })

    it('records an accepted sub-batch in the shared in-flight metrics until it settles', async () => {
        // Regression: the processor autoscaler reads ingestion_api_events_in_flight
        // and ingestion_api_event_seconds_in_flight_total, which only the HTTP
        // handler recorded — so pods serving the gRPC transport looked idle to
        // KEDA and the worker HPA metric read 0.
        // The metrics are process-global, so assert deltas against a baseline.
        const baseline = {
            batches: await metricValue('ingestion_api_batches_in_flight'),
            events: await metricValue('ingestion_api_events_in_flight'),
            eventSeconds: await metricValue('ingestion_api_event_seconds_in_flight_total'),
            processed: await metricValue('ingestion_api_batches_processed_total'),
            messages: await metricValue('ingestion_api_messages_processed_total'),
        }
        const source = new FrameSource()
        const collected = collect(server, source)

        source.push(hello())
        source.push(subBatch(1, [10, 11, 12]))
        await until(() => driver.feeds.length === 1)
        const streamId = driver.feeds[0].streamId
        expect(await metricValue('ingestion_api_batches_in_flight')).toBe(baseline.batches + 1)
        expect(await metricValue('ingestion_api_events_in_flight')).toBe(baseline.events + 3)

        // Completion alone is not settlement: the batch stays in flight until
        // its side effects are done, matching the HTTP path's response barrier.
        const settled = new Deferred<void>()
        driver.complete({ streamId, seq: 1, accepted: 3 }, settled.promise)
        await new Promise((resolve) => setTimeout(resolve, 20))
        expect(await metricValue('ingestion_api_events_in_flight')).toBe(baseline.events + 3)

        settled.resolve()
        await until(() => collected.acks.length === 1)
        expect(await metricValue('ingestion_api_batches_in_flight')).toBe(baseline.batches)
        expect(await metricValue('ingestion_api_events_in_flight')).toBe(baseline.events)
        expect(await metricValue('ingestion_api_event_seconds_in_flight_total')).toBeGreaterThan(baseline.eventSeconds)
        expect(await metricValue('ingestion_api_batches_processed_total')).toBe(baseline.processed + 1)
        expect(await metricValue('ingestion_api_messages_processed_total')).toBe(baseline.messages + 3)
    })

    it('a slow batch settlement does not block another sub-batch ack', async () => {
        // Regression: the pump awaited each completed batch's side effects
        // before pulling the next completion, head-of-line blocking every
        // stream's acks behind the slowest batch.
        const source = new FrameSource()
        const collected = collect(server, source)

        source.push(hello())
        source.push(subBatch(1, [10]))
        source.push(subBatch(2, [11]))
        await until(() => driver.feeds.length === 2)
        const streamId = driver.feeds[0].streamId

        driver.complete({ streamId, seq: 1, accepted: 1 }, new Promise<void>(() => {}))
        driver.complete({ streamId, seq: 2, accepted: 1 })
        await until(() => collected.acks.length === 1)
        expect(Number(collected.acks[0].seq)).toBe(2)
    })

    it('rebaselines the feed-order sentinel on a new assignment epoch instead of counting a violation', async () => {
        // A rebalance replays uncommitted (lower) offsets under the same
        // consumer id; scoping the sentinel by epoch is what keeps that from
        // counting as out-of-order — the false-positive class the HTTP
        // transport suffers from.
        const source = new FrameSource()
        collect(server, source)

        const before = await outOfOrderCount()
        source.push(hello())
        source.push(subBatch(1, [10, 11]))
        source.push(subBatch(2, [5, 6], { assignmentEpoch: 2n }))
        await until(() => driver.feeds.length === 2)
        expect(await outOfOrderCount()).toBe(before)

        // The same regression within one epoch is a real violation.
        source.push(subBatch(3, [2], { assignmentEpoch: 2n }))
        await until(() => driver.feeds.length === 3)
        expect(await outOfOrderCount()).toBe(before + 1)
    })

    it('refuses a stream past the total concurrency ceiling with ResourceExhausted', async () => {
        // The ceiling bounds total open streams so a peer that ignores the
        // per-session SETTINGS limit cannot make the server accumulate streams
        // without bound. It must refuse cleanly, not crash or hang.
        const capped = new WorkerIngestServer(
            { port: 0, maxConcurrentBatches: 4, capacityRetryMs: 1, pumpIdleMs: 1, maxStreams: 1 },
            { driver, feedOrderSentinel: sentinel, onFatal }
        )
        await capped.start()
        try {
            const held = new FrameSource()
            const first = collect(capped, held)
            await until(() => capped.streamCount === 1)

            const rejected = collect(capped, new FrameSource())
            await rejected.ended
            expect(rejected.error?.code).toBe(Code.ResourceExhausted)
            expect(capped.streamCount).toBe(1)

            held.end()
            await first.ended
        } finally {
            await capped.stop()
        }
    })
})
