import { HealthCheckResult } from '../../../types'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { CyclotronV2IdempotentOutcome } from '../cyclotron-v2/types'

export type ConsumeBatchFn = (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>

export type IdempotentInvocation = { invocation: CyclotronJobInvocation; fingerprint: string }

/**
 * Common interface for job queue backends (Kafka, postgres-v2).
 * Each consumer gets the specific implementation it needs — no shared router.
 */
export interface JobQueue {
    startAsProducer(): Promise<void>
    startAsConsumer(queue: CyclotronJobQueueKind, consumeBatch: ConsumeBatchFn): Promise<void>
    stopConsumer(): Promise<void>
    stopProducer(): Promise<void>
    isHealthy(): HealthCheckResult
    queueInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
    queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void>
    dequeueInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
    heartbeatInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
}

export interface IdempotentJobQueue extends JobQueue {
    queueInvocationsIdempotently(entries: IdempotentInvocation[]): Promise<CyclotronV2IdempotentOutcome[]>
    getIdempotencyKeyFingerprint(id: string): Promise<string | null>
}
