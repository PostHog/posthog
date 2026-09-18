/**
 * Events PostHog emits into a customer's project as the output of a product. Customer drop rules
 * (event filters and transformations) skip these: they are already paid for at the time they are
 * emitted, and the product reads them back from the events table, so dropping one only breaks that
 * product. There is no customer-facing opt-out; disabling the product stops the events instead.
 *
 * `$recording_observed`: Replay Vision surfaces observations from this event and uses it to skip
 * sessions a scanner already processed. Dropping it hides results and re-scans, and re-bills,
 * sessions.
 */
export const PROTECTED_INTERNAL_EVENTS: ReadonlySet<string> = new Set(['$recording_observed'])

export function isProtectedInternalEvent(eventName: string | undefined): boolean {
    return eventName !== undefined && PROTECTED_INTERNAL_EVENTS.has(eventName)
}
