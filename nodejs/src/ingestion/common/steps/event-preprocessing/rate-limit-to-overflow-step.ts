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

/** Returns the Kafka message key as a string, or null when the message has none. */
export function messageKeyString(message: Pick<Message, 'key'>): string | null {
    const rawKey = message.key
    if (rawKey === null || rawKey === undefined) {
        return null
    }
    const kafkaKey = typeof rawKey === 'string' ? rawKey : rawKey.toString('utf8')
    return kafkaKey.length === 0 ? null : kafkaKey
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
        const keyStats = new Map<string, { headersPerEvent: EventHeaders[]; firstTimestamp: number }>()

        for (const input of inputs) {
            const eventKey = messageKeyString(input.message)
            perInputKeys.push(eventKey)
            if (eventKey === null) {
                continue
            }

            const timestamp = input.headers.now?.getTime() ?? Date.now()
            const existing = keyStats.get(eventKey)
            if (existing) {
                existing.headersPerEvent.push(input.headers)
            } else {
                keyStats.set(eventKey, { headersPerEvent: [input.headers], firstTimestamp: timestamp })
            }
        }

        if (keyStats.size === 0) {
            return inputs.map((input) => ok(input))
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
            const eventKey = perInputKeys[index]
            if (eventKey !== null && keysToRedirect.has(eventKey)) {
                return redirect('rate_limit_exceeded', OVERFLOW_OUTPUT, preservePartitionLocality)
            }
            return ok(input)
        })
    }
}
