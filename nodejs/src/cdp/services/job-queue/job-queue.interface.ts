import { HealthCheckResult } from '../../../types'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'

export type ConsumeBatchFn = (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>

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
    cancelInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
    heartbeatInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
    /**
     * Persists `invocation`'s current state without releasing the job, so a
     * redelivery after a stall resumes from here instead of replaying
     * already-completed side effects (e.g. re-firing an outbound fetch).
     * Returns `false` if this worker no longer owns the job (backends without
     * lock stealing, e.g. Kafka, always return `true`).
     */
    checkpointInvocation(invocation: CyclotronJobInvocation): Promise<boolean>
}
