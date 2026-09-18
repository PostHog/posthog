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

function messageKeyString(message: Pick<Message, 'key'>): string | null {
    const rawKey = message.key
    if (rawKey === null || rawKey === undefined) {
        return null
    }
    const kafkaKey = typeof rawKey === 'string' ? rawKey : rawKey.toString('utf8')
    return kafkaKey.length === 0 ? null : kafkaKey
}

/**
 * The partition key a message concentrates on, shared by the rate limit and
 * TTL refresh steps so both sides of an overflow flag agree on its key: the
 * Kafka message key, or the `redirect-original-key` header a redirect stamps
 * when it drops the key, or `token:distinct_id` from headers — the key capture
 * builds for regular events.
 */
export function deriveOverflowKey(message: Pick<Message, 'key'>, headers: EventHeaders): string {
    return (
        messageKeyString(message) ??
        headers.redirect_original_key ??
        `${headers.token ?? ''}:${headers.distinct_id ?? ''}`
    )
}

/**
 * Rate-limits events to overflow, keyed on the Kafka message key — the partition
 * key capture computed. Runs before the body is parsed.
 *
 * The message key is the only correct unit for this limit: it is what
 * concentrates traffic on a partition. For regular events it is
 * `token:distinct_id`; for cookieless events it is `token:client_ip`, so one
 * IP's cookieless stream is budgeted as a single key even though every event
 * gets a fresh hashed distinct_id later in the pipeline.
 */
export function createRateLimitToOverflowStep<T extends RateLimitToOverflowStepInput>(
    preservePartitionLocality: boolean,
    overflowRedirectService?: OverflowRedirectService
) {
    return async function rateLimitToOverflowStep(inputs: T[]): Promise<PipelineResult<T, OverflowOutput>[]> {
        if (!overflowRedirectService || inputs.length === 0) {
            return inputs.map((input) => ok(input))
        }

        const perInputKeys: string[] = []
        const keyStats = new Map<string, { headersPerEvent: EventHeaders[]; firstTimestamp: number }>()

        for (const input of inputs) {
            const eventKey = deriveOverflowKey(input.message, input.headers)
            perInputKeys.push(eventKey)

            const timestamp = input.headers.now?.getTime() ?? Date.now()
            const existing = keyStats.get(eventKey)
            if (existing) {
                existing.headersPerEvent.push(input.headers)
            } else {
                keyStats.set(eventKey, { headersPerEvent: [input.headers], firstTimestamp: timestamp })
            }
        }

        const groups: OverflowEventGroup[] = Array.from(keyStats.entries()).map(
            ([key, { headersPerEvent, firstTimestamp }]) => ({
                key,
                headersPerEvent,
                firstTimestamp,
            })
        )
        const keysToRedirect = await overflowRedirectService.handleEventBatch(groups)

        return inputs.map((input, index) => {
            if (keysToRedirect.has(perInputKeys[index])) {
                return redirect('rate_limit_exceeded', OVERFLOW_OUTPUT, preservePartitionLocality)
            }
            return ok(input)
        })
    }
}
