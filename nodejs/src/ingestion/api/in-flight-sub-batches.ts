import { Counter, Gauge } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { KafkaDebugContext, aggregateKafkaDebugContexts } from '~/ingestion/framework/helpers'

import { AcceptedBatch, batchAccepted, batchFailed, batchProcessed, batchReleased } from './batch-metrics'

const stuckBatches = new Counter({
    name: 'ingestion_api_grpc_stuck_batches_total',
    help: 'Times a sub-batch stayed in flight past the stuck-batch deadline and started the stuck-batch shutdown',
})

const oldestInFlightAge = new Gauge({
    name: 'ingestion_api_grpc_oldest_in_flight_batch_age_seconds',
    help: 'Age of the oldest fed sub-batch that has not settled; the stuck-batch shutdown starts past its deadline',
})

export interface AdmittedSubBatch {
    streamId: number
    seq: number
    consumerId: string
    streamEpoch: string
    assignmentEpoch: string
    /** Coordinates only: the pipeline holds the payloads, and a copy here would live until the sub-batch settles. */
    messages: Pick<KafkaDebugContext, 'topic' | 'partition' | 'offset'>[]
}

export interface StuckSubBatch {
    key: string
    streamId: number
    inFlightMs: number
}

type Phase = 'feeding' | 'inPipeline' | 'settling'

const PHASE_ORDER: Record<Phase, number> = { feeding: 0, inPipeline: 1, settling: 2 }

interface Entry {
    subBatch: AdmittedSubBatch
    accounting: AcceptedBatch
    phase: Phase
    streamOpen: boolean
}

/**
 * Sub-batches from slot admission until they settle, including those of dead streams:
 *
 *   onFeeding -> feeding -> onAccepted -> inPipeline -> onCollected -> settling -> onSettled
 *
 * Phases only move forward, so the reader and the pump can report a sub-batch
 * in either order. Owns the in-flight accounting the processor autoscaler reads.
 */
export class InFlightSubBatches {
    private readonly entries = new Map<string, Entry>()
    private inPipeline = 0

    constructor(readonly stuckTimeoutMs: number) {}

    get size(): number {
        return this.entries.size
    }

    /** Sub-batches the pipeline holds that the pump has not collected. */
    get awaitingCollection(): number {
        return this.inPipeline
    }

    get checkIntervalMs(): number {
        return this.stuckTimeoutMs > 0 ? Math.min(this.stuckTimeoutMs / 4, 10_000) : 10_000
    }

    onFeeding(subBatch: AdmittedSubBatch): void {
        this.entries.set(key(subBatch.streamId, subBatch.seq), {
            subBatch,
            accounting: batchAccepted(subBatch.messages.length),
            phase: 'feeding',
            streamOpen: true,
        })
    }

    onAccepted(streamId: number, seq: number): void {
        const entry = this.entries.get(key(streamId, seq))
        if (entry) {
            this.moveTo(entry, 'inPipeline')
        }
    }

    onCollected(streamId: number, seq: number): void {
        const entry = this.entries.get(key(streamId, seq))
        if (entry) {
            this.moveTo(entry, 'settling')
        }
    }

    onSettled(streamId: number, seq: number, outcome: 'ok' | 'failed', processed: number): void {
        const entry = this.remove(streamId, seq)
        if (!entry) {
            return
        }
        if (outcome === 'ok') {
            batchProcessed(entry.accounting.acceptedAt, processed)
        } else {
            batchFailed()
        }
        batchReleased(entry.accounting)
    }

    /** Left without the pipeline accepting it; counts no error. */
    onAbandoned(streamId: number, seq: number): void {
        const entry = this.remove(streamId, seq)
        if (entry) {
            batchReleased(entry.accounting)
        }
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

    private moveTo(entry: Entry, phase: Phase): void {
        if (PHASE_ORDER[phase] <= PHASE_ORDER[entry.phase]) {
            return
        }
        if (entry.phase === 'inPipeline') {
            this.inPipeline--
        }
        if (phase === 'inPipeline') {
            this.inPipeline++
        }
        entry.phase = phase
    }

    private remove(streamId: number, seq: number): Entry | undefined {
        const entryKey = key(streamId, seq)
        const entry = this.entries.get(entryKey)
        if (!entry) {
            return undefined
        }
        this.moveTo(entry, 'settling')
        this.entries.delete(entryKey)
        return entry
    }
}

function key(streamId: number, seq: number): string {
    return `${streamId}:${seq}`
}
