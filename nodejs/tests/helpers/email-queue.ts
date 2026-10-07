import { DateTime } from 'luxon'

import { CdpCyclotronWorkerEmail } from '~/cdp/consumers/cdp-cyclotron-worker-email.consumer'
import { invocationToV2JobInit, v2JobToInvocation } from '~/cdp/services/job-queue/job-queue-postgres-v2'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, HogFlowInvocationContext } from '~/cdp/types'

import { TestRedisV2 } from './redis-v2'

export type EmailQueueInvocation = CyclotronJobInvocation & { state: HogFlowInvocationContext | null }

export class EmailQueueRoundTrip {
    constructor(private readonly worker: CdpCyclotronWorkerEmail) {}

    static encodeAndDecode(item: CyclotronJobInvocation): EmailQueueInvocation {
        const job = invocationToV2JobInit(item)
        const invocation = v2JobToInvocation({
            ...job,
            id: item.id,
            queueName: job.queueName ?? 'hogflow',
            priority: job.priority ?? 0,
            functionId: job.functionId ?? null,
            state: job.state ?? null,
            scheduled: DateTime.fromJSDate(job.scheduled!),
            created: DateTime.now(),
            parentRunId: job.parentRunId ?? null,
            distinctId: job.distinctId ?? null,
            personId: job.personId ?? null,
            actionId: job.actionId ?? null,
            transitionCount: 0,
            cancelRequestedAt: null,
            ack: jest.fn(),
            fail: jest.fn(),
            reschedule: jest.fn(),
            cancel: jest.fn(),
            heartbeat: jest.fn(),
            bulkCreateAndCheckIn: jest.fn(),
        })
        return { ...invocation, state: invocation.state as HogFlowInvocationContext | null }
    }

    async process(item: CyclotronJobInvocation): Promise<CyclotronJobInvocationResult<EmailQueueInvocation>> {
        const results = await this.worker.processInvocations([item])
        expect(results).toHaveLength(1)
        expect(results[0].error).toBeUndefined()
        return { ...results[0], invocation: EmailQueueRoundTrip.encodeAndDecode(results[0].invocation) }
    }
}

export class EmailRetryClock {
    constructor(
        private readonly redis: TestRedisV2,
        private readonly bucketKeys: string[]
    ) {}

    private async ageBucketTimestamps(elapsed: number): Promise<void> {
        await this.redis.useClient({ name: 'advance-email-buckets' }, async (client) => {
            for (const key of this.bucketKeys) {
                for (const field of ['ts', 'resv']) {
                    const timestamp = await client.hget(key, field)
                    if (timestamp !== null) {
                        await client.hset(key, field, Number(timestamp) - elapsed)
                    }
                }
            }
        })
    }

    async wake(item: CyclotronJobInvocation): Promise<void> {
        const wake = item.queueScheduledAt!.toMillis() + 1
        await this.ageBucketTimestamps(wake - Date.now())
        jest.spyOn(Date, 'now').mockReturnValue(wake)
    }
}
