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
    /**
     * Optional fallback for the email queue's scheduled→dequeueable transition.
     * The cyclotron janitor is the primary promoter; the email consumer calls
     * this on a slower interval as a safety net so a sick janitor can't
     * silently stop email delivery. Returns the number of rows promoted.
     * Implementations that don't back fair-dequeue can leave this undefined.
     */
    runScheduledPromotion?(batchSize: number): Promise<number>
}
