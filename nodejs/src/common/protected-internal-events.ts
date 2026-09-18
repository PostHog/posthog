/**
 * PostHog-emitted product events that customer event filters and transformations never drop.
 * Replay Vision reads `$recording_observed` back from the events table; dropping it hides
 * observations and re-scans sessions.
 */
export const PROTECTED_INTERNAL_EVENTS: ReadonlySet<string> = new Set(['$recording_observed'])

export function isProtectedInternalEvent(eventName: string | undefined): boolean {
    return eventName !== undefined && PROTECTED_INTERNAL_EVENTS.has(eventName)
}
