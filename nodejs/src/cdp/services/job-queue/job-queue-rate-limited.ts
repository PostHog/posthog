import { HealthCheckResult } from '../../../types'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { CyclotronV2BatchLimit } from '../cyclotron-v2'
import { CyclotronJobQueuePostgresV2 } from './job-queue-postgres-v2'
import { JobQueue } from './job-queue.interface'

/**
 * JobQueue decorator that gates dequeue behind a per-poll rate-limit hook.
 *
 * Wraps a `CyclotronJobQueuePostgresV2` (the only backend that supports
 * dynamic batch sizing today) and installs the hook when the consumer starts.
 * Other consumers receive the bare postgres-v2 queue and pay no cost for the
 * rate-limit code path.
 *
 * Typed against the concrete Postgres-V2 class on purpose: TypeScript stops you
 * from accidentally wrapping a Kafka or legacy-postgres queue, where the
 * underlying dynamic-batch-size mechanism doesn't exist.
 */
export class RateLimitedJobQueue implements JobQueue {
    constructor(
        private readonly inner: CyclotronJobQueuePostgresV2,
        private readonly getBatchLimit: () => Promise<CyclotronV2BatchLimit | undefined>
    ) {}

    public async startAsProducer(): Promise<void> {
        await this.inner.startAsProducer()
    }

    public async startAsConsumer(
        queue: CyclotronJobQueueKind,
        consumeBatch: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    ): Promise<void> {
        this.inner.setDynamicBatchLimit(this.getBatchLimit)
        await this.inner.startAsConsumer(queue, consumeBatch)
    }

    public async stopConsumer(): Promise<void> {
        await this.inner.stopConsumer()
    }

    public async stopProducer(): Promise<void> {
        await this.inner.stopProducer()
    }

    public isHealthy(): HealthCheckResult {
        return this.inner.isHealthy()
    }

    public async queueInvocations(invocations: CyclotronJobInvocation[]): Promise<void> {
        await this.inner.queueInvocations(invocations)
    }

    public async queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        await this.inner.queueInvocationResults(results)
    }

    public async dequeueInvocations(invocations: CyclotronJobInvocation[]): Promise<void> {
        await this.inner.dequeueInvocations(invocations)
    }

    public async cancelInvocations(invocations: CyclotronJobInvocation[]): Promise<void> {
        await this.inner.cancelInvocations(invocations)
    }
}
