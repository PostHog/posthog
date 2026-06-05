import { HealthCheckResult } from '../../../types'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'

export type ConsumeBatchFn = (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>

/**
 * Per-consumer overrides for batch size + empty-queue poll cadence. Used by
 * workers that need rate-limited dequeue (e.g. the SES email worker pacing
 * sends to AWS's per-second cap).
 */
export interface ConsumerOptions {
    batchMaxSize?: number
    pollDelayMs?: number
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
        options?: ConsumerOptions
    ): Promise<void>
    stopConsumer(): Promise<void>
    stopProducer(): Promise<void>
    isHealthy(): HealthCheckResult
    queueInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
    queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void>
    dequeueInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
    cancelInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
}
