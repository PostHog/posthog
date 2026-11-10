import { Counter, Gauge } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { aggregateKafkaDebugContexts } from '~/ingestion/framework/helpers'

import { AcceptedBatch } from './batch-metrics'
import { SerializedKafkaMessage } from './types'

const stuckBatches = new Counter({
    name: 'ingestion_api_grpc_stuck_batches_total',
    help: 'Times a sub-batch stayed in flight past the stuck-batch deadline and started the stuck-batch shutdown',
})

const oldestInFlightAge = new Gauge({
    name: 'ingestion_api_grpc_oldest_in_flight_batch_age_seconds',
    help: 'Age of the oldest fed sub-batch that has not settled; the stuck-batch shutdown starts past its deadline',
})

export interface FedBatch {
    accounting: AcceptedBatch
    streamId: number
    consumerId: string
    streamEpoch: string
    assignmentEpoch: string
    messages: SerializedKafkaMessage[]
}

export interface StuckBatchHost {
    fedBatches(): Iterable<[string, FedBatch]>
    /** False once the host drains, stops or fails. */
    serving(): boolean
    failed(): boolean
    streamOpen(streamId: number): boolean
    counts(): { fedBatches: number; openStreams: number; openSessions: number }
    /**
     * Fails `failStreams`, ends the others after their last ack, and resolves
     * `true` if all of them finished before `deadline`.
     */
    drain(failStreams: Set<number>, deadline: number): Promise<boolean>
}

export interface StuckBatchWatchdogOptions {
    timeoutMs: number
    drainTimeoutMs: number
    onStuck?: (error: Error) => void
    onStuckDrained?: (error: Error) => void
}

/**
 * A stuck sub-batch holds its slot until the process exits, so the worker
 * leaves the pool, lets the other sub-batches settle and ack, and then hands
 * the exit to the owner. To fail every stream at once would make consumers
 * replay healthy work.
 */
export class StuckBatchWatchdog {
    private timer: NodeJS.Timeout | null = null
    private drainDone = false

    constructor(
        private readonly options: StuckBatchWatchdogOptions,
        private readonly host: StuckBatchHost
    ) {}

    /** A stuck-batch drain already ran, so the host's own stop need not drain again. */
    get drained(): boolean {
        return this.drainDone
    }

    start(): void {
        const checkEveryMs = this.options.timeoutMs > 0 ? Math.min(this.options.timeoutMs / 4, 10_000) : 10_000
        this.timer = setInterval(() => this.check(), checkEveryMs)
        this.timer.unref()
    }

    stop(): void {
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = null
        }
    }

    private check(): void {
        const now = Date.now()
        const batches = [...this.host.fedBatches()]
        let oldestAcceptedAt = now
        for (const [, batch] of batches) {
            oldestAcceptedAt = Math.min(oldestAcceptedAt, batch.accounting.acceptedAt)
        }
        oldestInFlightAge.set((now - oldestAcceptedAt) / 1000)
        if (this.options.timeoutMs <= 0 || !this.host.serving()) {
            return
        }
        const stuck = batches.filter(([, batch]) => now - batch.accounting.acceptedAt > this.options.timeoutMs)
        if (stuck.length > 0) {
            this.trip(stuck, now)
        }
    }

    private trip(stuck: [string, FedBatch][], now: number): void {
        stuckBatches.inc()
        const error = new Error(
            `${stuck.length} sub-batch(es) in flight past the ${this.options.timeoutMs}ms stuck-batch deadline`
        )
        for (const [key, batch] of stuck) {
            logger.error('🧊', 'WorkerIngest sub-batch stuck', {
                key,
                inFlightMs: now - batch.accounting.acceptedAt,
                consumerId: batch.consumerId,
                streamEpoch: batch.streamEpoch,
                assignmentEpoch: batch.assignmentEpoch,
                ...aggregateKafkaDebugContexts(batch.messages),
                streamOpen: this.host.streamOpen(batch.streamId),
            })
        }

        this.options.onStuck?.(error)
        // The consumer resolves acks in seq order, so no ack behind a stuck sub-batch would resolve.
        const failStreams = new Set(stuck.map(([, batch]) => batch.streamId))
        const drained = this.host.drain(failStreams, now + this.options.drainTimeoutMs)
        logger.error('🧊', 'WorkerIngest stuck-batch shutdown: draining', {
            error: error.message,
            stuckBatches: stuck.length,
            ...this.host.counts(),
            drainTimeoutMs: this.options.drainTimeoutMs,
        })
        void this.finish(error, drained)
    }

    private async finish(error: Error, drained: Promise<boolean>): Promise<void> {
        const outcome = (await drained) ? 'drained' : 'timeout'
        if (this.host.failed()) {
            // The fatal path already failed the streams and told the owner.
            return
        }
        this.drainDone = true
        logger.error('🧊', `WorkerIngest stuck-batch shutdown: ${outcome}, exiting`, {
            error: error.message,
            ...this.host.counts(),
        })
        this.options.onStuckDrained?.(error)
    }
}
