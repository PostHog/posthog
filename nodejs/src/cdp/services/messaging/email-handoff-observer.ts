import { randomUUID } from 'crypto'
import { Counter } from 'prom-client'

import { RedisClient, RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { CyclotronJobInvocationHogFunction } from '../../types'
import { emailSendKey } from './email-wait'

// Covers a janitor reset of a running job and the longest reschedule of one send.
const HANDOFF_TTL_SECONDS = 60 * 60

// The pool has no acquire timeout and MX validation awaits it, so a slow Valkey must not pile up unawaited writes.
const MAX_IN_FLIGHT_OBSERVATIONS = 16

const EMAIL_SOURCES = ['transactional_api', 'workflow']
const OBSERVATION_RESULTS = ['first', 'duplicate', 'error', 'dropped'] as const
type ObservationResult = (typeof OBSERVATION_RESULTS)[number]

const emailDuplicateHandoffTotal = new Counter({
    name: 'cdp_email_duplicate_handoff_total',
    help: 'Fast-lane sends that SES accepted a second time within an hour, for the same send of a workflow step or transactional API call. Any increase is an email sent twice.',
    labelNames: ['source'],
})

const emailHandoffObservationsTotal = new Counter({
    name: 'cdp_email_handoff_observations_total',
    help: 'Accepted fast-lane sends checked for a duplicate handoff, by outcome. Errors and drops are sends the duplicate counter could not see.',
    labelNames: ['source', 'result'],
})

// increase() reads a series' first sample as its baseline, so a series created by the first event hides it.
for (const source of EMAIL_SOURCES) {
    emailDuplicateHandoffTotal.labels({ source }).inc(0)
    for (const result of OBSERVATION_RESULTS) {
        emailHandoffObservationsTotal.labels({ source, result }).inc(0)
    }
}

export class EmailHandoffObserver {
    private inFlight = 0

    constructor(private readonly valkey: RedisV2) {}

    public observe(invocation: CyclotronJobInvocationHogFunction, source: string): void {
        if (this.inFlight >= MAX_IN_FLIGHT_OBSERVATIONS) {
            emailHandoffObservationsTotal.inc({ source, result: 'dropped' })
            return
        }
        this.inFlight++
        void this.recordHandoff(invocation, source)
            .then((result) => emailHandoffObservationsTotal.inc({ source, result }))
            .catch((error: unknown) => {
                emailHandoffObservationsTotal.inc({ source, result: 'error' })
                captureException(error)
                logger.error('Failed to record an email handoff', { invocationId: invocation.id, error: String(error) })
            })
            .finally(() => {
                this.inFlight--
            })
    }

    private async recordHandoff(
        invocation: CyclotronJobInvocationHogFunction,
        source: string
    ): Promise<ObservationResult> {
        const key = `@posthog/email-handoff/${emailSendKey(invocation)}`
        // A repeat of the same job carries the same invocation id, and ioredis resends a write whose reply was lost,
        // so only a token unique to this observation tells a second handoff from a replay of this one.
        const token = randomUUID()
        // SET ... NX GET returns the value already stored, so one round trip tells a first handoff from a repeat.
        const previous = await this.valkey.useClient(
            { name: 'email-handoff', failOpen: false },
            (client: RedisClient) =>
                client.set(key, token, ['EX', String(HANDOFF_TTL_SECONDS), 'NX', 'GET']) as Promise<string | null>
        )
        if (previous === null || previous === token) {
            return 'first'
        }
        emailDuplicateHandoffTotal.inc({ source })
        logger.warn('SES accepted the same email send twice', { invocationId: invocation.id, key })
        return 'duplicate'
    }
}
