import { Counter, Gauge } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { aggregateKafkaDebugContexts } from '~/ingestion/framework/helpers'

import { AcceptedBatch, batchAccepted, batchFailed, batchProcessed, batchReleased } from './batch-metrics'
import { SerializedKafkaMessage } from './types'

const stuckBatches = new Counter({
    name: 'ingestion_api_grpc_stuck_batches_total',
    help: 'Times a sub-batch stayed in flight past the stuck-batch deadline and started the stuck-batch shutdown',
})

const oldestInFlightAge = new Gauge({
    name: 'ingestion_api_grpc_oldest_in_flight_batch_age_seconds',
    help: 'Age of the oldest fed sub-batch that has not settled; the stuck-batch shutdown starts past its deadline',
})

export interface FedSubBatch {
    streamId: number
    seq: number
    consumerId: string
    streamEpoch: string
    assignmentEpoch: string
    messages: SerializedKafkaMessage[]
}

export interface StuckSubBatch {
    key: string
    streamId: number
    inFlightMs: number
}

interface Entry {
    subBatch: FedSubBatch
    accounting: AcceptedBatch
    streamOpen: boolean
}

/**
 * Sub-batches the pipeline accepted and that have not settled, by
 * `streamId:seq`. Holds the in-flight accounting the processor autoscaler
 * reads. Kept apart from the streams, so a sub-batch whose stream died is
 * still collected and released when it settles.
 */
export class InFlightSubBatches {
    private readonly entries = new Map<string, Entry>()

    constructor(readonly stuckTimeoutMs: number) {}

    get size(): number {
        return this.entries.size
    }

    get checkIntervalMs(): number {
        return this.stuckTimeoutMs > 0 ? Math.min(this.stuckTimeoutMs / 4, 10_000) : 10_000
    }

    onFed(subBatch: FedSubBatch): void {
        this.entries.set(key(subBatch.streamId, subBatch.seq), {
            subBatch,
            accounting: batchAccepted(subBatch.messages.length),
            streamOpen: true,
        })
    }

    onSettled(streamId: number, seq: number, outcome: 'ok' | 'failed', processed: number): void {
        const entryKey = key(streamId, seq)
        const entry = this.entries.get(entryKey)
        if (!entry) {
            return
        }
        this.entries.delete(entryKey)
        if (outcome === 'ok') {
            batchProcessed(entry.accounting.acceptedAt, processed)
        } else {
            batchFailed()
        }
        batchReleased(entry.accounting)
    }

    onStreamEnded(streamId: number): void {
        for (const entry of this.entries.values()) {
            if (entry.subBatch.streamId === streamId) {
                entry.streamOpen = false
            }
        }
    }

    /** Sets the oldest-age gauge and returns the sub-batches past the deadline; none when the timeout is `0`. */
    findStuck(now: number): StuckSubBatch[] {
        let oldestAcceptedAt = now
        for (const entry of this.entries.values()) {
            oldestAcceptedAt = Math.min(oldestAcceptedAt, entry.accounting.acceptedAt)
        }
        oldestInFlightAge.set((now - oldestAcceptedAt) / 1000)
        if (this.stuckTimeoutMs <= 0) {
            return []
        }
        const stuck: StuckSubBatch[] = []
        for (const [entryKey, entry] of this.entries) {
            const inFlightMs = now - entry.accounting.acceptedAt
            if (inFlightMs > this.stuckTimeoutMs) {
                stuck.push({ key: entryKey, streamId: entry.subBatch.streamId, inFlightMs })
            }
        }
        return stuck
    }

    reportStuck(stuck: StuckSubBatch[]): void {
        stuckBatches.inc()
        for (const { key: entryKey, inFlightMs } of stuck) {
            const entry = this.entries.get(entryKey)
            if (!entry) {
                continue
            }
            const { subBatch } = entry
            logger.error('🧊', 'WorkerIngest sub-batch stuck', {
                key: entryKey,
                inFlightMs,
                consumerId: subBatch.consumerId,
                streamEpoch: subBatch.streamEpoch,
                assignmentEpoch: subBatch.assignmentEpoch,
                ...aggregateKafkaDebugContexts(subBatch.messages),
                streamOpen: entry.streamOpen,
            })
        }
    }
}

function key(streamId: number, seq: number): string {
    return `${streamId}:${seq}`
}
