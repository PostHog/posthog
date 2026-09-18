/**
 * PostHog-emitted product events that customer event filters and transformations never drop.
 *
 * $recording_observed: Replay Vision reads observations from this event
 */
export const PROTECTED_INTERNAL_EVENTS: ReadonlySet<string> = new Set(['$recording_observed'])

export function isProtectedInternalEvent(eventName: string | undefined): boolean {
    return eventName !== undefined && PROTECTED_INTERNAL_EVENTS.has(eventName)
}
