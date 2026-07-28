import { ErrorTrackingStackFrame } from './types'

/**
 * Stored/wire order for stack frames is canonical bottom-up: frames[0] is the
 * entry point and the last frame is the crash site (PostHog/sdk-specs — capture
 * exception, "Stack frame ordering"). The product displays the opposite way for
 * every platform: most recent call first, so the crash site leads. This is the
 * single place display order is decided — consumers of stored frames that need
 * the crash site should index from the end, not reverse.
 */
export function toDisplayOrderFrames(frames: ErrorTrackingStackFrame[]): ErrorTrackingStackFrame[] {
    return [...frames].reverse()
}
