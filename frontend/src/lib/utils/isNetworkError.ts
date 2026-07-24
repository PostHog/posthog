import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

/**
 * Recognizes a transient, outside-our-control fetch failure — a dropped connection, a request
 * aborted by navigation, a CORS rejection, or an ad blocker. The browser throws these as a bare
 * `TypeError` whose message varies by engine:
 *   - Chromium: `Failed to fetch`
 *   - WebKit/Safari: `Load failed`
 *   - Firefox: `NetworkError when attempting to fetch resource.`
 *
 * `isChunkLoadError` already recognizes the WebKit/Firefox wordings (they double as failed module
 * imports), so this reuses it and adds Chromium's plain `fetch` wording. A `SyntaxError` from
 * parsing a response body is NOT a network error and returns false, so real bugs keep flowing.
 */
export function isNetworkError(error: unknown): boolean {
    if (isChunkLoadError(error)) {
        return true
    }
    if (!error || typeof error !== 'object') {
        return false
    }
    const err = error as { name?: string; message?: string }
    const message = typeof err.message === 'string' ? err.message : ''
    return err.name === 'TypeError' && message.includes('Failed to fetch')
}
