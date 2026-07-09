import { dlq, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders } from '~/types'

/**
 * DLQs any event whose header `event` name is not in the allow list.
 * Reads from the parsed Kafka headers so it can run before message-body
 * parsing — use in a consumer's pipeline to enforce that only its
 * target event type(s) flow through. Anything else is misrouted and
 * goes to the DLQ for investigation. Events with no `event` header
 * pass through (no name to match against).
 */
export function createAllowEventsStep<T extends { headers: EventHeaders }>(
    allowed: readonly string[]
): ProcessingStep<T, T> {
    const allowedSet = new Set(allowed)
    return function allowEventsStep(input) {
        const name = input.headers.event
        if (name === undefined || allowedSet.has(name)) {
            return Promise.resolve(ok(input))
        }
        return Promise.resolve(dlq('event_not_in_allowlist'))
    }
}
