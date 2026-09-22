import { EventHeaders } from '~/types'

/**
 * PostHog-emitted product events that customer event filters and transformations never drop.
 *
 * $recording_observed: Replay Vision reads observations from this event
 */
export const PROTECTED_INTERNAL_EVENTS: ReadonlySet<string> = new Set(['$recording_observed'])

export function isProtectedInternalEvent(headers: Pick<EventHeaders, 'event' | 'internal_producer'>): boolean {
    return (
        headers.internal_producer === true &&
        headers.event !== undefined &&
        PROTECTED_INTERNAL_EVENTS.has(headers.event)
    )
}
