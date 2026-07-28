import { dlq, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders } from '~/types'

export interface DeniedEvents {
    /** Exact event names to deny. */
    eventNames?: readonly string[]
    /** Event name prefixes to deny (e.g. `$ai_`). */
    eventPrefixes?: readonly string[]
}

/**
 * DLQs any event whose header `event` name is denied, either by exact
 * name or by prefix. Reads from the parsed Kafka headers so it can run
 * before message-body parsing — use in a consumer's pipeline to block
 * event types that belong in a different consumer. Anything matching
 * is misrouted and goes to the DLQ for investigation. Events with no
 * `event` header pass through (no name to match against).
 */
export function createDenyEventsStep<T extends { headers: EventHeaders }>(denied: DeniedEvents): ProcessingStep<T, T> {
    const deniedNames = new Set(denied.eventNames ?? [])
    const deniedPrefixes = denied.eventPrefixes ?? []
    return function denyEventsStep(input) {
        const name = input.headers.event
        if (name !== undefined && (deniedNames.has(name) || deniedPrefixes.some((prefix) => name.startsWith(prefix)))) {
            return Promise.resolve(dlq('event_in_denylist'))
        }
        return Promise.resolve(ok(input))
    }
}
