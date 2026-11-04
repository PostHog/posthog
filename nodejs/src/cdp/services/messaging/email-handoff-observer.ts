import { Counter } from 'prom-client'

import { RedisClient, RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { CyclotronJobInvocationHogFunction } from '../../types'
import { emailSendKey } from './email-wait'

// Covers a janitor reset of a running job and the longest reschedule of one send.
const HANDOFF_TTL_SECONDS = 60 * 60

const emailDuplicateHandoffTotal = new Counter({
    name: 'cdp_email_duplicate_handoff_total',
    help: 'Fast-lane sends that SES accepted a second time within an hour, for the same send of a workflow step or transactional API call. Any increase is an email sent twice.',
    labelNames: ['source'],
})

// increase() reads a series' first sample as its baseline, so a series created by the first duplicate hides it.
for (const source of ['transactional_api', 'workflow']) {
    emailDuplicateHandoffTotal.labels({ source }).inc(0)
}

export class EmailHandoffObserver {
    constructor(private readonly valkey: RedisV2) {}

    public observe(invocation: CyclotronJobInvocationHogFunction, source: string): void {
        void this.recordHandoff(invocation, source).catch((error: unknown) => {
            captureException(error)
            logger.error('Failed to record an email handoff', { invocationId: invocation.id, error: String(error) })
        })
    }

    private async recordHandoff(invocation: CyclotronJobInvocationHogFunction, source: string): Promise<void> {
        const key = `@posthog/email-handoff/${emailSendKey(invocation)}`
        // SET ... NX GET returns the value already stored, so one round trip tells a first handoff from a repeat.
        const previous = await this.valkey.useClient(
            { name: 'email-handoff', failOpen: true },
            (client: RedisClient) =>
                client.set(key, invocation.id, ['EX', String(HANDOFF_TTL_SECONDS), 'NX', 'GET']) as Promise<
                    string | null
                >
        )
        if (previous !== null) {
            emailDuplicateHandoffTotal.inc({ source })
            logger.warn('SES accepted the same email send twice', { invocationId: invocation.id, key })
        }
    }
}
