import { HealthCheckResult } from '../../../types'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import type { PoisonQuarantine } from '../poison-quarantine/poison-quarantine'

export type ConsumeBatchFn = (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>

/**
 * Common interface for job queue backends (Kafka, postgres-v2).
 * Each consumer gets the specific implementation it needs — no shared router.
 */
export interface JobQueue {
    startAsProducer(): Promise<void>
    startAsConsumer(
        queue: CyclotronJobQueueKind,
        consumeBatch: ConsumeBatchFn,
        poisonQuarantine?: PoisonQuarantine
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
