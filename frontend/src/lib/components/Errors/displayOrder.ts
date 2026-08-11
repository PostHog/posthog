import { dayjs } from 'lib/dayjs'

import { ErrorTrackingStackFrame } from './types'

/**
 * Stored/wire order for stack frames is canonical bottom-up: frames[0] is the
 * entry point and the last frame is the crash site (PostHog/sdk-specs — capture
 * exception, "Stack frame ordering"). The product displays the opposite way for
 * every platform: most recent call first, so the crash site leads.
 *
 * Exception: events ingested before the pipeline's wire-order normalization
 * (deployed 2026-07-09 ~16:10 UTC) from SDKs that emitted crash-first stacks are stored crash-first
 * and must not be reversed — their stored order already matches the display
 * policy. That population is frozen and disappears as event retention expires,
 * at which point `isStoredCrashFirst` and this special case can be deleted.
 */
export function toDisplayOrderFrames(
    frames: ErrorTrackingStackFrame[],
    storedCrashFirst: boolean = false
): ErrorTrackingStackFrame[] {
    return storedCrashFirst ? [...frames] : [...frames].reverse()
}

// SDKs that emitted crash-first frames before their canonical-order flip; the
// pipeline normalized their payloads from WIRE_ORDER_NORMALIZATION_DATE onward.
const CRASH_FIRST_LIBS = new Set([
    'posthog-android',
    'posthog-flutter',
    'posthog-php',
    'posthog-go',
    'posthog-rs',
    'posthog-elixir',
    'posthog-java',
    'posthog-server',
])

// Best-effort boundary: compares the event's occurrence timestamp against the
// cloud rollout date of the pipeline normalization. Events that straddle the
// boundary (offline-buffered mobile deliveries, imports) and self-hosted
// deployments that upgraded later can be misclassified — the cost is reversed
// display order on those old events only, and the population shrinks to zero
// with event retention. A precise answer would need a persisted storage-order
// marker, which pre-dates this code; not worth adding for a transient case.
const WIRE_ORDER_NORMALIZATION_DATE = '2026-07-09T16:10:00Z'

export function isStoredCrashFirst(lib: string | undefined, timestamp: string | undefined): boolean {
    if (!lib || !timestamp || !CRASH_FIRST_LIBS.has(lib)) {
        return false
    }
    // parse rather than string-compare: event timestamps arrive in several ISO
    // forms (fractional seconds, +00:00 offsets) that do not sort lexically
    const parsed = dayjs(timestamp)
    return parsed.isValid() && parsed.isBefore(WIRE_ORDER_NORMALIZATION_DATE)
}
