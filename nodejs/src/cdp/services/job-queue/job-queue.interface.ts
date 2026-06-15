import { HealthCheckResult } from '../../../types'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'

export type ConsumeBatchFn = (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>

/**
 * Per-poll batch sizing hook used to gate dequeue behind a rate limit.
 *
 *   `{ limit: 0, sleepMs }`  → skip this poll, sleep for `sleepMs`.
 *   `{ limit: N }`           → dequeue up to `min(N, batchMaxSize)` rows.
 *   `undefined` return       → fall back to static `batchMaxSize`.
 *
 * Resolved once per consumer loop iteration before the SQL runs. Backends that
 * can't size a fetch dynamically (Kafka) ignore this and use the static max.
 */
export type BatchLimitDecision = { limit: number; sleepMs?: number }
export type GetBatchLimitFn = () => Promise<BatchLimitDecision | undefined>

export interface StartAsConsumerOptions {
    getBatchLimit?: GetBatchLimitFn
}

/**
 * Common interface for job queue backends (Kafka, postgres-v2).
 * Each consumer gets the specific implementation it needs — no shared router.
 */
export interface JobQueue {
    startAsProducer(): Promise<void>
    startAsConsumer(
        queue: CyclotronJobQueueKind,
        consumeBatch: ConsumeBatchFn,
        options?: StartAsConsumerOptions
    ): Promise<void>
    stopConsumer(): Promise<void>
    stopProducer(): Promise<void>
    isHealthy(): HealthCheckResult
    queueInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
    queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void>
    dequeueInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
    cancelInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
}
