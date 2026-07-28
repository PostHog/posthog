import { dlq, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders } from '~/types'

export interface AllowedEvents {
    /** Exact event names to allow. */
    eventNames?: readonly string[]
    /** Event name prefixes to allow (e.g. `$ai_`). */
    eventPrefixes?: readonly string[]
}

/**
 * DLQs any event whose header `event` name is not allowed, either by
 * exact name or by prefix. Reads from the parsed Kafka headers so it
 * can run before message-body parsing — use in a consumer's pipeline
 * to enforce that only its target event type(s) flow through. Anything
 * else is misrouted and goes to the DLQ for investigation. Events with
 * no `event` header pass through (no name to match against).
 */
export function createAllowEventsStep<T extends { headers: EventHeaders }>(
    allowed: AllowedEvents
): ProcessingStep<T, T> {
    const allowedNames = new Set(allowed.eventNames ?? [])
    const allowedPrefixes = allowed.eventPrefixes ?? []
    return function allowEventsStep(input) {
        const name = input.headers.event
        if (name === undefined || allowedNames.has(name) || allowedPrefixes.some((prefix) => name.startsWith(prefix))) {
            return Promise.resolve(ok(input))
        }
        return Promise.resolve(dlq('event_not_in_allowlist'))
    }
}
