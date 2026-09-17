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
 * Refreshes the key the main lane flagged, using the same key derivation as the
 * rate limit step (`deriveOverflowKey`) so flag and refresh always agree.
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

        // Group events by partition key for batch TTL refresh
        const keyStats = new Map<string, { headersPerEvent: EventHeaders[]; firstTimestamp: number }>()

        for (const { message, headers } of inputs) {
            const eventKey = deriveOverflowKey(message, headers)
            const timestamp = headers.now?.getTime() ?? Date.now()

            const existing = keyStats.get(eventKey)
            if (existing) {
                existing.headersPerEvent.push(headers)
            } else {
                keyStats.set(eventKey, { headersPerEvent: [headers], firstTimestamp: timestamp })
            }
        }

        const groups: OverflowEventGroup[] = Array.from(keyStats.entries()).map(
            ([key, { headersPerEvent, firstTimestamp }]) => ({
                key,
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
