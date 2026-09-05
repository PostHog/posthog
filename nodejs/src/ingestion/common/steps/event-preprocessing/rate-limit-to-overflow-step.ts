import { Message } from 'node-rdkafka'

import { OVERFLOW_OUTPUT, OverflowOutput } from '~/common/outputs'
import {
    OverflowEventGroup,
    OverflowRedirectService,
} from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import { PipelineResult, ok, redirect } from '~/ingestion/framework/results'
import { EventHeaders } from '~/types'

export interface RateLimitToOverflowStepInput {
    message: Pick<Message, 'key'>
    headers: EventHeaders
}

/**
 * Splits the Kafka message key into the (token, distinctId) shape the overflow
 * redirect service flags in Redis. Capture builds the key as `<token>:<suffix>`,
 * where the suffix is the distinct_id for regular events and the client IP for
 * cookieless events.
 */
export function deriveOverflowKey(
    message: Pick<Message, 'key'>,
    headers: EventHeaders
): { token: string; distinctId: string } | null {
    const rawKey = message.key
    if (rawKey === null || rawKey === undefined) {
        return null
    }
    const kafkaKey = typeof rawKey === 'string' ? rawKey : rawKey.toString('utf8')
    if (kafkaKey.length === 0) {
        return null
    }

    const token = headers.token ?? ''
    const prefix = `${token}:`
    if (kafkaKey.startsWith(prefix)) {
        return { token, distinctId: kafkaKey.slice(prefix.length) }
    }
    return { token, distinctId: kafkaKey }
}

/**
 * Rate-limits events to overflow, keyed on the Kafka message key — the partition
 * key capture computed. Runs before the body is parsed.
 *
 * The message key is the only correct unit for this limit: it is what
 * concentrates traffic on a partition. For regular events it is
 * `token:distinct_id`; for cookieless events it is `token:client_ip`, so one
 * IP's cookieless stream is budgeted as a single key even though every event
 * gets a fresh hashed distinct_id later in the pipeline. Events without a
 * message key are spread round-robin by capture, cannot concentrate on a
 * partition, and pass through unlimited.
 */
export function createRateLimitToOverflowStep<T extends RateLimitToOverflowStepInput>(
    preservePartitionLocality: boolean,
    overflowRedirectService?: OverflowRedirectService
) {
    return async function rateLimitToOverflowStep(inputs: T[]): Promise<PipelineResult<T, OverflowOutput>[]> {
        if (!overflowRedirectService || inputs.length === 0) {
            return inputs.map((input) => ok(input))
        }

        const perInputKeys: (string | null)[] = []
        const keyStats = new Map<
            string,
            { token: string; distinctId: string; headersPerEvent: EventHeaders[]; firstTimestamp: number }
        >()

        for (const input of inputs) {
            const derived = deriveOverflowKey(input.message, input.headers)
            if (!derived) {
                perInputKeys.push(null)
                continue
            }

            const eventKey = `${derived.token}:${derived.distinctId}`
            perInputKeys.push(eventKey)

            const timestamp = input.headers.now?.getTime() ?? Date.now()
            const existing = keyStats.get(eventKey)
            if (existing) {
                existing.headersPerEvent.push(input.headers)
            } else {
                keyStats.set(eventKey, { ...derived, headersPerEvent: [input.headers], firstTimestamp: timestamp })
            }
        }

        if (keyStats.size === 0) {
            return inputs.map((input) => ok(input))
        }

        const groups: OverflowEventGroup[] = Array.from(keyStats.values()).map(
            ({ token, distinctId, headersPerEvent, firstTimestamp }) => ({
                key: { token, distinctId },
                headersPerEvent,
                firstTimestamp,
            })
        )
        const keysToRedirect = await overflowRedirectService.handleEventBatch(groups)

        return inputs.map((input, index) => {
            const eventKey = perInputKeys[index]
            if (eventKey !== null && keysToRedirect.has(eventKey)) {
                return redirect('rate_limit_exceeded', OVERFLOW_OUTPUT, preservePartitionLocality)
            }
            return ok(input)
        })
    }
}
