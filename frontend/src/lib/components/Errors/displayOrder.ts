import { ErrorTrackingStackFrame } from './types'

/**
 * Stored/wire order for stack frames is canonical bottom-up: frames[0] is the
 * entry point and the last frame is the crash site (PostHog/sdk-specs — capture
 * exception, "Stack frame ordering"). The product displays the opposite way for
 * every platform: most recent call first, so the crash site leads.
 *
 * Exception: events ingested before the pipeline's wire-order normalization
 * (2026-07-09) from SDKs that emitted crash-first stacks are stored crash-first
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

const WIRE_ORDER_NORMALIZATION_DATE = '2026-07-10T00:00:00Z'

export function isStoredCrashFirst(lib: string | undefined, timestamp: string | undefined): boolean {
    if (!lib || !timestamp || !CRASH_FIRST_LIBS.has(lib)) {
        return false
    }
    return timestamp < WIRE_ORDER_NORMALIZATION_DATE
}
