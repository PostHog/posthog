/**
 * Cross-surface session stitching: PostHog Desktop appends the current posthog-js session ID to
 * links it opens in the browser, so events and recordings from both surfaces share one
 * $session_id. A journey like "prompt in Desktop, continue in the web app" then queries as one
 * session and plays back as a single replay.
 * The sender lives in products/desktop/packages/shared/src/session-stitching.ts; the param name
 * must match on both sides.
 */
export const POSTHOG_SESSION_ID_URL_PARAM = '__posthog_session_id'

const SESSION_ID_MAX_AGE_MS = 24 * 60 * 60 * 1000
const SESSION_ID_CLOCK_SKEW_MS = 2 * 60 * 1000

// posthog-js requires bootstrap.sessionID to be a UUIDv7; it derives the session start time from
// the embedded timestamp. Its own parsing accepts non-hex garbage (NaN timestamp disables the 24h
// rotation), so validate strictly here and treat the param as untrusted input.
const UUID_V7_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function uuidV7TimestampMs(sessionId: string): number {
    return parseInt(sessionId.slice(0, 8) + sessionId.slice(9, 13), 16)
}

/**
 * Read and remove the session ID param placed on the URL by PostHog Desktop.
 * Always strips the param when present (so it never reaches `$current_url`, the recording, or a
 * copy-pasted URL), but only returns the value when it is a plausible live session: a strict
 * UUIDv7 whose embedded timestamp is within the last 24 hours (posthog-js caps sessions at 24h).
 * Must run before `posthog.init` so the returned value can be passed as `bootstrap.sessionID`,
 * and before `initKea()` so the router never sees the param.
 */
export function consumeCrossSurfaceSessionId(): string | null {
    const params = new URLSearchParams(window.location.search)
    const sessionId = params.get(POSTHOG_SESSION_ID_URL_PARAM)
    if (sessionId === null) {
        return null
    }

    const url = new URL(window.location.href)
    url.searchParams.delete(POSTHOG_SESSION_ID_URL_PARAM)
    window.history.replaceState(window.history.state, '', url.toString())

    if (!UUID_V7_REGEX.test(sessionId)) {
        return null
    }
    const timestamp = uuidV7TimestampMs(sessionId)
    const now = Date.now()
    if (timestamp < now - SESSION_ID_MAX_AGE_MS || timestamp > now + SESSION_ID_CLOCK_SKEW_MS) {
        return null
    }
    return sessionId
}
