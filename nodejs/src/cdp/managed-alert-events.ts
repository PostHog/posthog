// Mirror of `posthog/cdp/internal_events.py`. The managed-alert event boundary and the legacy
// insight-alert exemption must match the Python side exactly, so keep the two in sync.
export const MANAGED_ALERT_EVENT_PATTERN = /^\$[a-z0-9_]+_alert_(firing|resolved|errored|auto_disabled|match)$/
export const LEGACY_INSIGHT_ALERT_EVENT = '$insight_alert_firing'

/** Return whether an internal event is reserved for an alert-owned destination. */
export function isManagedAlertInternalEvent(eventName: unknown): boolean {
    return (
        typeof eventName === 'string' &&
        eventName !== LEGACY_INSIGHT_ALERT_EVENT &&
        MANAGED_ALERT_EVENT_PATTERN.test(eventName)
    )
}
