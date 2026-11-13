import type { KafkaConsumerConfig } from '~/common/kafka/consumer'
import { ProducerMessage } from '~/common/kafka/producer'

import { HealthCheckResult } from '../../../types'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import type { CrashGuard } from '../poison-batch/crash-guard'

export type ConsumeBatchFn = (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>

/** Only the Kafka queue reads these, because they act on its consumer and the messages it fetches. */
export type ConsumerOptions = Pick<KafkaConsumerConfig, 'fetchBatchSize' | 'maxBackgroundTasks'> & {
    // A factory, because the guard keys its counts by the consumer group, which the queue names. produce goes
    // through the queue's own producer.
    crashGuard?: (consumer: { groupId: string; produce: (message: ProducerMessage) => Promise<void> }) => CrashGuard
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
