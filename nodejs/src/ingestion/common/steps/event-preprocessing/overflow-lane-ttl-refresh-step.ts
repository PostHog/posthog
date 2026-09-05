import { Message } from 'node-rdkafka'

import {
    OverflowEventGroup,
    OverflowRedirectService,
} from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { EventHeaders } from '~/types'

import { deriveOverflowKey } from './rate-limit-to-overflow-step'

export interface OverflowLaneTTLRefreshStepInput {
    message: Pick<Message, 'key'>
    headers: EventHeaders
}

/**
 * Creates a step that refreshes TTL for overflow lane events.
 * Used in the overflow lane to keep Redis flags alive while events are being processed.
 * Once events stop coming, the flags expire and future events return to the main lane.
 *
 * Uses the Kafka message key when the redirect preserved it, matching the key the
 * main lane flagged. A redirect without partition locality nulls the key; then the
 * refresh falls back to `token:headers.distinct_id`, which matches the flag for
 * regular events. Cookieless flags are keyed on the client IP, which the fallback
 * cannot reconstruct — those flags expire after the Redis TTL, and the main lane's
 * still-drained bucket re-flags the key on the next event burst.
 *
 * If no service is provided, this step is a no-op (passthrough).
 */
export function createOverflowLaneTTLRefreshStep<T extends OverflowLaneTTLRefreshStepInput>(
    overflowRedirectService?: OverflowRedirectService
) {
    return function overflowLaneTTLRefreshStep(inputs: T[]): Promise<PipelineResult<T>[]> {
        if (inputs.length === 0 || !overflowRedirectService) {
            return Promise.resolve(inputs.map((input) => ok(input)))
        }

        // Group events by token:distinct_id for batch TTL refresh
        const keyStats = new Map<
            string,
            { token: string; distinctId: string; headersPerEvent: EventHeaders[]; firstTimestamp: number }
        >()

        for (const { message, headers } of inputs) {
            const derived = deriveOverflowKey(message, headers) ?? {
                token: headers.token ?? '',
                distinctId: headers.distinct_id ?? '',
            }
            const eventKey = `${derived.token}:${derived.distinctId}`
            const timestamp = headers.now?.getTime() ?? Date.now()

            const existing = keyStats.get(eventKey)
            if (existing) {
                existing.headersPerEvent.push(headers)
            } else {
                keyStats.set(eventKey, { ...derived, headersPerEvent: [headers], firstTimestamp: timestamp })
            }
        }

        const groups: OverflowEventGroup[] = Array.from(keyStats.values()).map(
            ({ token, distinctId, headersPerEvent, firstTimestamp }) => ({
                key: { token, distinctId },
                headersPerEvent,
                firstTimestamp,
            })
        )

        // TTL refresh doesn't affect routing, so attach it as a pipeline side effect
        // instead of blocking the pipeline on a Redis write.
        const refreshPromise = overflowRedirectService.handleEventBatch(groups)

        return Promise.resolve(inputs.map((input) => ok(input, [refreshPromise])))
    }
}
