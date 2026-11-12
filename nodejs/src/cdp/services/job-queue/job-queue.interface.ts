import { HealthCheckResult } from '../../../types'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import type { CrashGuard } from '../poison-batch/crash-guard'

export type ConsumeBatchFn = (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>

/** Only the Kafka queue reads these, because they act on its consumer and the messages it fetches. */
export type ConsumerOptions = {
    // A factory, because the guard keys its counts by the consumer group, which the queue names.
    crashGuard?: (consumer: { groupId: string }) => CrashGuard
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
    heartbeatInvocations(invocations: CyclotronJobInvocation[]): Promise<void>
    deferInvocations(deferrals: { invocation: CyclotronJobInvocation; scheduledAt: Date }[]): Promise<void>
}
