/**
 * A failed `fetch` throws a `TypeError` whose message varies by browser:
 *   - Chrome/Edge: `Failed to fetch`
 *   - Firefox:     `NetworkError when attempting to fetch resource.`
 *   - Safari:      `Load failed`
 * These are transient and outside our control (connection blips, offline, aborted or ad-blocked
 * requests), so they're noise in error tracking rather than real defects. A genuine bug in the same
 * code path surfaces as a different error type, which we still want to capture.
 */
export function isNetworkError(error: unknown): boolean {
    if (!(error instanceof Error)) {
        return false
    }
    return error.name === 'TypeError' && /failed to fetch|network\s*error|load failed/i.test(error.message)
}
