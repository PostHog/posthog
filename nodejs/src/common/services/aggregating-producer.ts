import { IngestionOutput } from '../../ingestion/outputs/ingestion-output'
import { logger } from '../../utils/logger'

export interface AggregatingProducerOptions<T> {
    /** Aggregation key — items sharing this key are merged in-memory. */
    key: (item: T) => string
    /** Combine `existing` and `incoming` for one key. Should not mutate. */
    merge: (existing: T, incoming: T) => T
    /** Build the Kafka message value at flush time, after all merging is done. */
    serialize: (item: T) => Buffer
    /**
     * Hard cap on unique buffered keys before a flush is triggered automatically.
     * The flush runs in the background — `queue()` returns immediately. Callers
     * can use `waitForBackpressure()` to throttle. Default: 1000.
     */
    maxBufferSize?: number
    /**
     * If set, periodically drains the buffer every N ms. Off by default — the
     * caller is expected to call `flush()` (and `shutdown()` at process exit)
     * unless they opt in here.
     */
    backgroundFlushIntervalMs?: number
}

const DEFAULT_MAX_BUFFER_SIZE = 1000

/**
 * Generic in-memory aggregating wrapper around a single Kafka output.
 *
 * Buffers items keyed by `options.key(item)`, merging colliding entries via
 * `options.merge`. On `flush()` (manual, buffer-full, background timer, or
 * `shutdown`), drains the buffer, serializes each entry, and produces a single
 * batch through the injected `IngestionOutput`.
 *
 * Lifecycle:
 * - `queue` is synchronous. Hitting `maxBufferSize` triggers a background flush.
 * - `flush()` returns once every entry queued before the call has been delivered.
 *   Concurrent calls behind an in-flight flush share a single chained follow-up.
 * - `waitForBackpressure()` resolves when any in-flight flush settles.
 * - `shutdown()` stops the background timer (if enabled), drains, and rejects
 *   further `queue` calls. Idempotent.
 */
export class AggregatingProducer<T> {
    private buffer = new Map<string, T>()
    private inFlight: Promise<void> | null = null
    private pending: Promise<void> | null = null
    private timer?: ReturnType<typeof setInterval>
    private isShutdown = false

    private readonly maxBufferSize: number

    constructor(
        private readonly output: IngestionOutput,
        private readonly options: AggregatingProducerOptions<T>
    ) {
        this.maxBufferSize = options.maxBufferSize ?? DEFAULT_MAX_BUFFER_SIZE

        if (options.backgroundFlushIntervalMs !== undefined && options.backgroundFlushIntervalMs > 0) {
            this.timer = setInterval(() => {
                this.flush().catch((err) =>
                    logger.error('🔴', 'AggregatingProducer background flush failed', { error: err })
                )
            }, options.backgroundFlushIntervalMs)
        }
    }

    /** Aggregate one item into the buffer. Synchronous. */
    queue(item: T): void {
        if (this.isShutdown) {
            throw new Error('AggregatingProducer.queue called after shutdown')
        }
        const key = this.options.key(item)
        const existing = this.buffer.get(key)
        this.buffer.set(key, existing ? this.options.merge(existing, item) : item)
        if (this.buffer.size >= this.maxBufferSize) {
            // Fire-and-forget; callers can await `waitForBackpressure()` to throttle.
            void this.flush().catch((err) =>
                logger.error('🔴', 'AggregatingProducer buffer-full flush failed', { error: err })
            )
        }
    }

    /**
     * Drain the buffer and produce to the output. Returns a promise that resolves
     * once every entry queued before the call has been delivered.
     *
     * If a flush is already in flight, the new call chains behind it so no
     * caller misses entries that landed during the previous flush.
     */
    flush(): Promise<void> {
        if (this.inFlight) {
            // Make sure exactly one follow-up flush is scheduled and have all
            // callers in this window share its promise.
            if (!this.pending) {
                this.pending = this.inFlight.then(() => {
                    this.pending = null
                    return this.flush()
                })
            }
            return this.pending
        }
        if (this.buffer.size === 0) {
            return Promise.resolve()
        }
        const drained = this.buffer
        this.buffer = new Map()
        this.inFlight = this._produce(drained).finally(() => {
            this.inFlight = null
        })
        return this.inFlight
    }

    /** Resolve when any in-flight flush settles. No-op when nothing is in flight. */
    async waitForBackpressure(): Promise<void> {
        if (this.inFlight) {
            await this.inFlight.catch(() => undefined)
        }
    }

    /**
     * Stop the background timer (if enabled), drain the buffer one last time,
     * and reject any further `queue` calls. Idempotent.
     */
    async shutdown(): Promise<void> {
        if (this.isShutdown) {
            await this.waitForBackpressure()
            return
        }
        this.isShutdown = true
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = undefined
        }
        await this.flush()
    }

    private async _produce(drained: Map<string, T>): Promise<void> {
        // No partition key by default — aggregating callers tend to write to
        // topics that ClickHouse re-aggregates anyway, where round-robin is fine.
        const messages = [...drained.values()].map((item) => ({
            value: this.options.serialize(item),
            key: null,
        }))
        await this.output.queueMessages(messages)
    }
}
