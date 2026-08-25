import { create } from '@bufbuild/protobuf'
import { Code, ConnectError, ConnectRouter, HandlerContext } from '@connectrpc/connect'
import { connectNodeAdapter } from '@connectrpc/connect-node'
import * as http2 from 'node:http2'
import { Counter, Gauge } from 'prom-client'

import {
    IngestStreamRequest,
    IngestStreamResponse,
    IngestStreamResponseSchema,
    KafkaMessage,
    StreamHello,
    StreamReadySchema,
    SubBatchAckSchema,
    SubBatchStatus,
    WorkerIngest,
} from '~/common/generated/ingestion-worker/ingestion/worker/v1/worker_pb'
import { logger } from '~/common/utils/logger'
import { FeedResult } from '~/ingestion/framework/batching-pipeline'

import { FeedOrderSentinel } from './feed-order-sentinel'
import { SerializedKafkaMessage } from './types'

const grpcStreams = new Gauge({
    name: 'ingestion_api_grpc_streams',
    help: 'Open WorkerIngest streams (one per connected consumer process)',
})

const grpcSubBatches = new Counter({
    name: 'ingestion_api_grpc_sub_batches_total',
    help: 'Sub-batches resolved on the gRPC ingest path',
    labelNames: ['status'],
})

const grpcMessagesProcessed = new Counter({
    name: 'ingestion_api_grpc_messages_processed_total',
    help: 'Messages acked on the gRPC ingest path',
})

const grpcProtocolErrors = new Counter({
    name: 'ingestion_api_grpc_protocol_errors_total',
    help: 'Streams closed for protocol violations (missing hello, seq gap or regression)',
    labelNames: ['kind'],
})

const grpcFeedSlotWaiters = new Gauge({
    name: 'ingestion_api_grpc_feed_slot_waiters',
    help: 'Streams waiting for a pipeline batch slot (FIFO admission queue depth)',
})

const grpcCapacityRetries = new Counter({
    name: 'ingestion_api_grpc_capacity_retries_total',
    help: 'Feeds rejected at_capacity despite holding an admission slot (capacity accounting drift)',
})

const grpcConnectionsRejected = new Counter({
    name: 'ingestion_api_grpc_connections_rejected_total',
    help: 'Sessions or streams refused because a concurrency cap was hit',
    labelNames: ['reason'],
})

/** A batch the pipeline finished processing. */
export interface CompletedSubBatch {
    streamId: number
    seq: number
    accepted: number
    /**
     * Resolves when the batch's side effects are durably done — the ack
     * barrier. Kept as a promise (not awaited inside `next()`) so the pump
     * can settle many completed batches concurrently: one batch's slow side
     * effects must not head-of-line block every other stream's acks.
     */
    settled: Promise<void>
}

/**
 * Pipeline mechanics behind the stream protocol. The server owns ordering,
 * acks, capacity admission, and stream lifecycle; the driver owns how a
 * sub-batch enters the shared pipeline and when its processing is durably
 * done (`settled`).
 */
export interface StreamIngestDriver {
    feed(streamId: number, seq: number, messages: SerializedKafkaMessage[]): Promise<FeedResult>
    next(): Promise<CompletedSubBatch | null>
}

export interface WorkerIngestServerOptions {
    port: number
    /**
     * Pipeline batch capacity, mirrored by the server's FIFO admission queue:
     * feeds are granted in arrival order across all streams, so a busy stream
     * cannot starve another (a retry race here wedged whole consumers).
     * Must match the gRPC pipeline's `concurrentBatches`.
     */
    maxConcurrentBatches: number
    /** Fallback delay if the pipeline still reports at_capacity despite an admission slot. */
    capacityRetryMs?: number
    /** Delay before re-pumping when the pipeline reports drained but sub-batches are still in flight. */
    pumpIdleMs?: number
    /**
     * Total concurrent streams the server will hold open across all sessions.
     * The topology is roughly one stream per connected consumer, so this is a
     * generous ceiling that only trips on misbehaviour — a stream past it is
     * refused with ResourceExhausted rather than accumulating unbounded.
     */
    maxStreams?: number
    /** Total concurrent HTTP/2 sessions; a session past this is destroyed on open. */
    maxSessions?: number
    /** Per-session stream limit, advertised via HTTP/2 SETTINGS and enforced by Node. */
    maxStreamsPerSession?: number
    /** Per-session memory budget in MB (HTTP/2 `maxSessionMemory`). */
    sessionMemoryMb?: number
    /**
     * Largest gRPC message the server will deserialize; bigger frames get
     * ResourceExhausted. The consumer targets 10 MiB sub-batches, but an
     * over-limit frame is replayed verbatim, so keep generous headroom.
     */
    readMaxBytes?: number
    /** Idle time before a session with no activity is closed, reaping dead peers. */
    sessionIdleTimeoutMs?: number
    /**
     * How long stop() waits for fed sub-batches to settle and their acks to
     * flush before failing what remains. Without the drain, every scale-down
     * makes consumers replay work the pipeline already processed.
     */
    drainTimeoutMs?: number
}

/** Thrown from `FifoSlots.acquire` when the waiting stream is cancelled. */
class SlotAcquisitionAborted extends Error {}

/**
 * FIFO slot queue: capacity grants go to waiters in arrival order. A freed
 * slot passes directly to the oldest waiter instead of returning to a pool a
 * newer arrival could win.
 *
 * A waiter can be cancelled via its `AbortSignal`: a stream that disconnects
 * while parked here is removed from the queue, so a freed slot skips it and
 * goes to a live stream instead of feeding work that can never be acked.
 */
class FifoSlots {
    private available: number
    private waiters: (() => void)[] = []

    constructor(capacity: number) {
        this.available = capacity
    }

    acquire(signal?: AbortSignal): Promise<void> {
        if (signal?.aborted) {
            return Promise.reject(new SlotAcquisitionAborted())
        }
        if (this.available > 0) {
            this.available--
            return Promise.resolve()
        }
        grpcFeedSlotWaiters.inc()
        return new Promise<void>((resolve, reject) => {
            const grant = (): void => {
                signal?.removeEventListener('abort', onAbort)
                grpcFeedSlotWaiters.dec()
                resolve()
            }
            const onAbort = (): void => {
                const index = this.waiters.indexOf(grant)
                if (index === -1) {
                    // Already granted a slot; the caller's post-acquire check
                    // hands it back. Nothing queued to remove here.
                    return
                }
                this.waiters.splice(index, 1)
                grpcFeedSlotWaiters.dec()
                reject(new SlotAcquisitionAborted())
            }
            this.waiters.push(grant)
            signal?.addEventListener('abort', onAbort, { once: true })
        })
    }

    release(): void {
        const next = this.waiters.shift()
        if (next) {
            next()
            return
        }
        this.available++
    }
}

interface WorkerIngestServerDeps {
    driver: StreamIngestDriver
    /** Shared with the HTTP path so both transports check the same invariant. */
    feedOrderSentinel?: FeedOrderSentinel
    /**
     * A pipeline error poisons the shared pipeline for every stream, so the
     * server fails all streams and hands the error up — the owner mirrors the
     * HTTP path's crash-and-rebuild contract.
     */
    onFatal: (error: Error) => void
}

/** Unbounded FIFO handed from the pump to each stream's response generator. */
class AckQueue {
    private items: IngestStreamResponse[] = []
    private waiter: {
        resolve: (value: IteratorResult<IngestStreamResponse>) => void
        reject: (err: Error) => void
    } | null = null
    private done = false
    private error: Error | null = null

    push(item: IngestStreamResponse): void {
        if (this.done) {
            return
        }
        if (this.waiter) {
            const { resolve } = this.waiter
            this.waiter = null
            resolve({ value: item, done: false })
            return
        }
        this.items.push(item)
    }

    /** No more acks will arrive; the generator completes after draining. */
    end(): void {
        this.done = true
        if (this.waiter && this.items.length === 0) {
            const { resolve } = this.waiter
            this.waiter = null
            resolve({ value: undefined, done: true })
        }
    }

    /** Fail the consuming generator (stream error towards the consumer). */
    fail(error: Error): void {
        this.error = error
        this.done = true
        if (this.waiter) {
            const { reject } = this.waiter
            this.waiter = null
            reject(error)
        }
    }

    [Symbol.asyncIterator](): AsyncIterator<IngestStreamResponse> {
        return {
            next: (): Promise<IteratorResult<IngestStreamResponse>> => {
                if (this.items.length > 0) {
                    return Promise.resolve({ value: this.items.shift()!, done: false })
                }
                if (this.error) {
                    return Promise.reject(this.error)
                }
                if (this.done) {
                    return Promise.resolve({ value: undefined, done: true })
                }
                return new Promise((resolve, reject) => {
                    this.waiter = { resolve, reject }
                })
            },
        }
    }
}

interface StreamState {
    id: number
    hello: StreamHello | null
    nextSeq: number
    inFlight: Set<number>
    readerDone: boolean
    acks: AckQueue
}

export function grpcMessageToSerialized(message: KafkaMessage): SerializedKafkaMessage {
    return {
        topic: message.topic,
        partition: message.partition,
        offset: Number(message.offset),
        timestamp: Number(message.timestamp),
        key: message.key ?? null,
        value: message.value ?? null,
        headers: message.headers,
    }
}

function readyFrame(): IngestStreamResponse {
    return create(IngestStreamResponseSchema, {
        msg: { case: 'ready', value: create(StreamReadySchema, {}) },
    })
}

function okAck(seq: number, accepted: number): IngestStreamResponse {
    return create(IngestStreamResponseSchema, {
        msg: {
            case: 'ack',
            value: create(SubBatchAckSchema, { seq: BigInt(seq), status: SubBatchStatus.OK, accepted }),
        },
    })
}

function failedAck(seq: number, error: string): IngestStreamResponse {
    return create(IngestStreamResponseSchema, {
        msg: {
            case: 'ack',
            value: create(SubBatchAckSchema, { seq: BigInt(seq), status: SubBatchStatus.FAILED, error }),
        },
    })
}

/**
 * Serves `ingestion.worker.v1.WorkerIngest`: the ordered streaming transport
 * from the Rust ingestion consumer.
 *
 * Ordering: each stream has one reader loop that awaits the pipeline's
 * acceptance of a sub-batch before reading the next frame, so feed order
 * equals stream order — and HTTP/2 flow control backpressures the consumer
 * while the pipeline is at capacity, replacing the HTTP path's 503s.
 * Processing stays concurrent behind the feed; acks are pushed as batches
 * complete, out of order, correlated by `seq`.
 *
 * Failure: any pipeline failure poisons the shared pipeline, so every open
 * stream is failed and `onFatal` fires — the consumer treats a broken stream
 * as a dead lane and replays its un-acked tail.
 */
export class WorkerIngestServer {
    private server: http2.Http2Server | null = null
    private streams = new Map<number, StreamState>()
    private nextStreamId = 1
    private stopped = false
    private draining = false
    private readonly drainAbort = new AbortController()
    private readonly stopAbort = new AbortController()
    private sessions = new Set<http2.ServerHttp2Session>()
    private fatalError: Error | null = null
    private pumpTask: Promise<void> | null = null
    private wakePump: (() => void) | null = null
    private readonly capacityRetryMs: number
    private readonly pumpIdleMs: number
    private readonly maxStreams: number
    private readonly maxSessions: number
    private readonly maxStreamsPerSession: number
    private readonly sessionMemoryMb: number
    private readonly sessionIdleTimeoutMs: number
    private readonly readMaxBytes: number
    private readonly drainTimeoutMs: number
    private sessionCount = 0
    private readonly slots: FifoSlots

    constructor(
        private options: WorkerIngestServerOptions,
        private deps: WorkerIngestServerDeps
    ) {
        this.capacityRetryMs = options.capacityRetryMs ?? 20
        this.pumpIdleMs = options.pumpIdleMs ?? 20
        this.maxStreams = options.maxStreams ?? 256
        this.maxSessions = options.maxSessions ?? 256
        this.maxStreamsPerSession = options.maxStreamsPerSession ?? 8
        this.sessionMemoryMb = options.sessionMemoryMb ?? 64
        this.sessionIdleTimeoutMs = options.sessionIdleTimeoutMs ?? 300_000
        this.readMaxBytes = options.readMaxBytes ?? 32 * 1024 * 1024
        this.drainTimeoutMs = options.drainTimeoutMs ?? 15_000
        this.slots = new FifoSlots(options.maxConcurrentBatches)
    }

    async start(): Promise<void> {
        this.pumpTask = this.runPump()
        this.server = http2.createServer(
            {
                // Cap per-session streams (advertised via SETTINGS, enforced by
                // Node) and per-session buffered memory, so one peer cannot fan
                // out or buffer without bound. Total sessions and streams are
                // bounded separately below and in ingestStream.
                settings: { maxConcurrentStreams: this.maxStreamsPerSession },
                maxSessionMemory: this.sessionMemoryMb,
            },
            connectNodeAdapter({
                readMaxBytes: this.readMaxBytes,
                routes: (router: ConnectRouter) => {
                    router.service(WorkerIngest, {
                        ingestStream: (requests, context: HandlerContext) =>
                            this.ingestStream(requests, context.signal),
                    })
                },
            })
        )
        this.server.on('session', (session) => this.onSession(session))
        await new Promise<void>((resolve, reject) => {
            this.server!.once('error', reject)
            this.server!.listen(this.options.port, () => {
                this.server!.removeListener('error', reject)
                logger.info('🛜', `WorkerIngest gRPC server listening on port ${this.options.port}`)
                resolve()
            })
        })
    }

    /**
     * Bounds concurrent sessions and reaps idle ones. A session past the cap is
     * destroyed on open; an idle session is closed so a dead or slow peer cannot
     * hold resources indefinitely. The `error` listener keeps a session-level
     * error from crashing the process (an EventEmitter error with no listener
     * throws).
     */
    private onSession(session: http2.ServerHttp2Session): void {
        if (this.sessionCount >= this.maxSessions) {
            grpcConnectionsRejected.inc({ reason: 'max_sessions' })
            session.destroy()
            return
        }
        this.sessionCount++
        this.sessions.add(session)
        session.setTimeout(this.sessionIdleTimeoutMs, () => session.close())
        session.on('error', (error) => logger.warn('🛜', 'WorkerIngest session error', { error }))
        session.once('close', () => {
            this.sessionCount--
            this.sessions.delete(session)
        })
    }

    /**
     * Drains before tearing down: fed sub-batches settle and their acks flush,
     * so a scale-down does not make consumers replay already-processed work.
     */
    async stop(): Promise<void> {
        this.draining = true
        this.drainAbort.abort()
        // A poisoned pipeline never settles, so skip straight to teardown.
        const deadline = this.fatalError ? 0 : Date.now() + this.drainTimeoutMs
        while (this.totalInFlight() > 0 && Date.now() < deadline) {
            await sleep(10)
        }
        this.stopped = true
        this.stopAbort.abort()
        for (const stream of this.streams.values()) {
            if (stream.inFlight.size === 0) {
                stream.acks.end()
            } else {
                stream.acks.fail(new ConnectError('server shutting down', Code.Unavailable))
            }
        }
        this.wake()
        // http2's close() waits for every session to end and consumers hold
        // theirs open, so send a graceful GOAWAY instead of waiting.
        for (const session of this.sessions) {
            session.close()
        }
        if (this.server) {
            await new Promise<void>((resolve) => this.server!.close(() => resolve()))
            this.server = null
        }
        // A poisoned pipeline can leave the pump blocked in a next() that will
        // never resolve — bound the wait instead of hanging shutdown on it.
        await Promise.race([this.pumpTask, sleep(5_000)])
    }

    /** Open stream count, exposed for tests. */
    get streamCount(): number {
        return this.streams.size
    }

    private wake(): void {
        if (this.wakePump) {
            const wake = this.wakePump
            this.wakePump = null
            wake()
        }
    }

    private totalInFlight(): number {
        let total = 0
        for (const stream of this.streams.values()) {
            total += stream.inFlight.size
        }
        return total
    }

    /**
     * The single pump: drains completed batches from the driver and routes
     * acks to their stream. One loop per server — completed batches carry
     * their stream id, so streams never contend over the pipeline's results.
     */
    private async runPump(): Promise<void> {
        while (!this.stopped) {
            if (this.totalInFlight() === 0) {
                await new Promise<void>((resolve) => {
                    this.wakePump = resolve
                })
                continue
            }
            try {
                const completed = await this.raceStopped(this.deps.driver.next())
                if (completed === undefined) {
                    return
                }
                if (completed === null) {
                    // The pipeline drained between feeds while acked work is
                    // still being registered — yield briefly and re-pump.
                    await sleep(this.pumpIdleMs)
                    continue
                }
                // Settle concurrently: the pump goes straight back to the
                // pipeline while this batch's side effects finish, so one slow
                // batch cannot head-of-line block other streams' acks.
                this.settleAndAck(completed)
            } catch (error) {
                this.fatal(error instanceof Error ? error : new Error(String(error)))
                return
            }
        }
    }

    /**
     * Like Promise.race(work, stop) resolving `undefined` on stop, but without
     * race's per-call listener leak: the stop listener is removed once work
     * settles.
     */
    private raceStopped<T>(work: Promise<T>): Promise<T | undefined> {
        if (this.stopAbort.signal.aborted) {
            return Promise.resolve(undefined)
        }
        return new Promise((resolve, reject) => {
            const onStop = (): void => resolve(undefined)
            this.stopAbort.signal.addEventListener('abort', onStop, { once: true })
            work.then(
                (value) => {
                    this.stopAbort.signal.removeEventListener('abort', onStop)
                    resolve(value)
                },
                (error) => {
                    this.stopAbort.signal.removeEventListener('abort', onStop)
                    reject(error)
                }
            )
        })
    }

    private settleAndAck(completed: CompletedSubBatch): void {
        void (async () => {
            try {
                await completed.settled
            } catch (error) {
                this.slots.release()
                this.fatal(error instanceof Error ? error : new Error(String(error)))
                return
            }
            // The batch's admission slot frees only once its side effects are
            // durably done, matching the HTTP path's response barrier.
            this.slots.release()
            this.ackCompleted(completed)
        })()
    }

    private ackCompleted(completed: CompletedSubBatch): void {
        const stream = this.streams.get(completed.streamId)
        if (!stream) {
            // The stream died while its sub-batch was processing; the consumer
            // replays the un-acked tail on its next stream.
            return
        }
        stream.inFlight.delete(completed.seq)
        stream.acks.push(okAck(completed.seq, completed.accepted))
        grpcSubBatches.inc({ status: 'ok' })
        grpcMessagesProcessed.inc(completed.accepted)
        this.maybeFinish(stream)
    }

    private maybeFinish(stream: StreamState): void {
        if (stream.readerDone && stream.inFlight.size === 0) {
            stream.acks.end()
        }
    }

    /** Stop reading without failing the stream; pending acks still flush. */
    private finishReader(stream: StreamState, unfedSeq?: number): void {
        if (unfedSeq !== undefined) {
            stream.inFlight.delete(unfedSeq)
        }
        stream.readerDone = true
        this.maybeFinish(stream)
    }

    /**
     * A pipeline failure poisons the shared pipeline (same contract as the
     * HTTP handler's fatal path): fail every stream so consumers tear down
     * their lanes and replay, then hand the error to the owner to shut down.
     */
    private fatal(error: Error): void {
        if (this.fatalError) {
            return
        }
        this.fatalError = error
        logger.error('💥', 'WorkerIngest pipeline failed — failing all streams', { error: error.message })
        for (const stream of this.streams.values()) {
            stream.acks.fail(new ConnectError(`ingest pipeline failed: ${error.message}`, Code.Internal))
        }
        this.deps.onFatal(error)
    }

    async *ingestStream(
        requests: AsyncIterable<IngestStreamRequest>,
        signal?: AbortSignal
    ): AsyncIterable<IngestStreamResponse> {
        if (this.fatalError) {
            throw new ConnectError('ingest pipeline is poisoned', Code.Unavailable)
        }
        if (this.draining) {
            throw new ConnectError('server shutting down', Code.Unavailable)
        }
        // Total stream ceiling across every session: the per-session SETTINGS cap
        // bounds one peer, this bounds the whole server if a peer ignores it.
        if (this.streams.size >= this.maxStreams) {
            grpcConnectionsRejected.inc({ reason: 'max_streams' })
            throw new ConnectError('too many concurrent streams', Code.ResourceExhausted)
        }
        const stream: StreamState = {
            id: this.nextStreamId++,
            hello: null,
            nextSeq: 1,
            inFlight: new Set(),
            readerDone: false,
            acks: new AckQueue(),
        }
        this.streams.set(stream.id, stream)
        grpcStreams.inc()

        // connect-node defers response headers until the first response
        // message and the consumer's stream-open awaits them, so greet first.
        stream.acks.push(readyFrame())

        const reader = this.runReader(stream, requests, signal)
        // Reader failures surface through the ack queue.
        swallowRejection(reader)

        try {
            for await (const ack of stream.acks) {
                yield ack
            }
            // Normal completion: propagate a reader outcome the queue may not
            // have carried (it can only fail after a waiter is registered).
            await reader
        } finally {
            this.streams.delete(stream.id)
            grpcStreams.dec()
            this.wake()
        }
    }

    private async runReader(
        stream: StreamState,
        requests: AsyncIterable<IngestStreamRequest>,
        signal?: AbortSignal
    ): Promise<void> {
        // Admission waits abort on disconnect and on drain: either way the
        // sub-batch was never fed, so the consumer replays it for free.
        const admissionSignal = signal ? AbortSignal.any([signal, this.drainAbort.signal]) : this.drainAbort.signal
        try {
            for await (const request of requests) {
                if (this.draining) {
                    this.finishReader(stream)
                    return
                }
                if (request.msg.case === 'hello') {
                    if (stream.hello) {
                        throw this.protocolError(stream, 'duplicate_hello', 'received a second hello frame')
                    }
                    stream.hello = request.msg.value
                    continue
                }
                if (request.msg.case !== 'subBatch') {
                    throw this.protocolError(stream, 'unknown_frame', 'frame is neither hello nor sub_batch')
                }
                if (!stream.hello) {
                    throw this.protocolError(stream, 'missing_hello', 'received a sub-batch before the hello frame')
                }

                const subBatch = request.msg.value
                const seq = Number(subBatch.seq)
                if (seq !== stream.nextSeq) {
                    throw this.protocolError(
                        stream,
                        'seq_mismatch',
                        `expected seq ${stream.nextSeq}, got ${seq} — frames were lost or reordered`
                    )
                }
                stream.nextSeq++

                if (subBatch.messages.length === 0) {
                    // An empty feed never completes a batch, so ack it directly.
                    stream.acks.push(okAck(seq, 0))
                    continue
                }

                const serialized = subBatch.messages.map(grpcMessageToSerialized)
                // The sentinel's sender scope includes both epochs, so
                // reconnects and rebalances rebaseline instead of counting
                // legitimate replays as violations.
                this.deps.feedOrderSentinel?.check(
                    serialized,
                    `${stream.hello.consumerId}#${stream.hello.streamEpoch}#${subBatch.assignmentEpoch}`,
                    subBatch.replay
                )

                // Await admission before reading the next frame: stream order
                // becomes feed order, and the stalled read backpressures the
                // consumer via HTTP/2 flow control. Slots are granted in FIFO
                // order because a retry race here let busy streams starve
                // quiet ones, wedging whole consumers.
                stream.inFlight.add(seq)
                try {
                    await this.slots.acquire(admissionSignal)
                } catch (error) {
                    if (error instanceof SlotAcquisitionAborted) {
                        this.finishReader(stream, seq)
                        return
                    }
                    throw error
                }
                if (signal?.aborted) {
                    // Cancelled between the slot grant and here: hand the slot
                    // straight back so a live stream gets it, and stop reading.
                    this.slots.release()
                    return
                }
                let feedAccepted = false
                try {
                    while (true) {
                        if (this.draining) {
                            this.finishReader(stream, seq)
                            return
                        }
                        const result = await this.feedGuarded(stream, seq, serialized)
                        if (result.ok) {
                            feedAccepted = true
                            break
                        }
                        if (result.kind === 'at_capacity') {
                            // The admission queue mirrors pipeline capacity, so
                            // this means the two drifted — count it and retry.
                            grpcCapacityRetries.inc()
                            await sleep(this.capacityRetryMs)
                            continue
                        }
                        stream.inFlight.delete(seq)
                        stream.acks.push(failedAck(seq, result.reason))
                        grpcSubBatches.inc({ status: 'failed' })
                        throw new ConnectError(`sub-batch ${seq} rejected: ${result.reason}`, Code.Internal)
                    }
                } finally {
                    // An accepted feed hands its slot to the pump, which
                    // releases it after the batch settles; every other exit
                    // must give the slot back here.
                    if (!feedAccepted) {
                        this.slots.release()
                    }
                }
                this.wake()
            }
            this.finishReader(stream)
        } catch (error) {
            stream.readerDone = true
            const connectError = error instanceof ConnectError ? error : new ConnectError(String(error), Code.Internal)
            stream.acks.fail(connectError)
            throw connectError
        }
    }

    /** Feed through the driver, converting a thrown pipeline error into the fatal path. */
    private async feedGuarded(
        stream: StreamState,
        seq: number,
        messages: SerializedKafkaMessage[]
    ): Promise<FeedResult> {
        try {
            return await this.deps.driver.feed(stream.id, seq, messages)
        } catch (error) {
            this.fatal(error instanceof Error ? error : new Error(String(error)))
            throw new ConnectError('ingest pipeline failed', Code.Internal)
        }
    }

    private protocolError(stream: StreamState, kind: string, message: string): ConnectError {
        grpcProtocolErrors.inc({ kind })
        logger.warn('⚠️', 'WorkerIngest protocol violation', { streamId: stream.id, kind, message })
        return new ConnectError(message, Code.FailedPrecondition)
    }
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

/** For promises whose failure is reported elsewhere; an unobserved rejection would crash the process. */
function swallowRejection(promise: Promise<unknown>): void {
    promise.catch(() => {})
}
