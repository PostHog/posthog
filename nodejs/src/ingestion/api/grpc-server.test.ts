import { create } from '@bufbuild/protobuf'
import { Code, ConnectError } from '@connectrpc/connect'
import { register } from 'prom-client'

import {
    IngestStreamRequest,
    IngestStreamRequestSchema,
    IngestStreamResponse,
    KafkaMessageSchema,
    StreamHelloSchema,
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

    complete(batch: CompletedSubBatch): void {
        const waiter = this.nextWaiters.shift()
        if (waiter) {
            waiter.resolve(batch)
            return
        }
        this.completions.push(batch)
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
    acks: IngestStreamResponse[]
    error: ConnectError | null
    ended: Promise<void>
}

function collect(server: WorkerIngestServer, source: FrameSource): Collected {
    const collected: Collected = { acks: [], error: null, ended: Promise.resolve() }
    collected.ended = (async () => {
        try {
            for await (const ack of server.ingestStream(source)) {
                collected.acks.push(ack)
            }
        } catch (error) {
            collected.error = error as ConnectError
        }
    })()
    return collected
}

async function until(condition: () => boolean): Promise<void> {
    const deadline = Date.now() + 5_000
    while (!condition()) {
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
            { port: 0, capacityRetryMs: 1, pumpIdleMs: 1 },
            { driver, feedOrderSentinel: sentinel, onFatal }
        )
        await server.start()
    })

    afterEach(async () => {
        await server.stop()
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
})
