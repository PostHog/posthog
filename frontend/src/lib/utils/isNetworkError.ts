/**
 * Recognizes a network-level `fetch` failure — the request never completed, so there is no HTTP
 * response to inspect. This happens when the user is offline, navigated away mid-request, or an
 * ad blocker / privacy extension killed the request. The browser throws a native `TypeError` whose
 * message varies by engine:
 *   - Chromium: `Failed to fetch`
 *   - Firefox:  `NetworkError when attempting to fetch resource.`
 *   - Safari:   `Load failed`
 * `handleFetch` in api.ts rewraps this into an `ApiError` with no `status`, stringifying the message
 * to e.g. `TypeError: Failed to fetch`, so we match on the message rather than the constructor.
 *
 * These failures are transient and outside our control, so callers can soft-handle them instead of
 * reporting noise to error tracking. A genuine bug (a malformed response, a thrown `SyntaxError`)
 * surfaces with a different message or an HTTP status, and is left to propagate.
 */
export function isNetworkError(error: unknown): boolean {
    if (error instanceof TypeError) {
        return true
    }
    if (!error || typeof error !== 'object') {
        return false
    }
    const message =
        typeof (error as { message?: unknown }).message === 'string' ? (error as { message: string }).message : ''
    return /failed to fetch|networkerror when attempting to fetch|load failed/i.test(message)
}
