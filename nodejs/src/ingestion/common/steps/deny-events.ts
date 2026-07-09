import { dlq, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders } from '~/types'

/**
 * DLQs any event whose header `event` name is in the deny list. Reads
 * from the parsed Kafka headers so it can run before message-body
 * parsing — use in a consumer's pipeline to block specific event types
 * that belong in a different consumer. Anything matching the list is
 * misrouted and goes to the DLQ for investigation. Events with no
 * `event` header pass through (no name to match against).
 */
export function createDenyEventsStep<T extends { headers: EventHeaders }>(
    denied: readonly string[]
): ProcessingStep<T, T> {
    const deniedSet = new Set(denied)
    return function denyEventsStep(input) {
        const name = input.headers.event
        if (name !== undefined && deniedSet.has(name)) {
            return Promise.resolve(dlq('event_in_denylist'))
        }
        return Promise.resolve(ok(input))
    }
}
