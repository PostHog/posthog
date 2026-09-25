/**
 * Sends one event straight to the capture API, without posthog-js. Code in the entry chunk runs
 * before the SDK loads, because the SDK lives in the App chunk, and a caller that reloads the
 * page needs a transport that survives the unload.
 *
 * Fire-and-forget: reporting must never make the failure it reports worse.
 */
export function captureViaBeacon(event: string, properties: Record<string, unknown>): void {
    try {
        const apiKey = window.JS_POSTHOG_API_KEY
        if (!apiKey) {
            return // capture is opted out for this instance
        }
        const host = window.JS_POSTHOG_HOST || window.location.origin
        const distinctId = readPersistedDistinctId(apiKey)
        const payload = JSON.stringify({
            api_key: apiKey,
            event,
            distinct_id: distinctId || `anonymous-${Date.now()}`,
            properties: {
                $current_url: window.location.href,
                // A synthetic distinct id is unique per event, so a person profile built from it
                // would be junk. Send the event without one instead.
                $process_person_profile: !!distinctId,
                ...properties,
            },
        })
        // A string body goes out as text/plain: CORS-safelisted (no preflight) and accepted by
        // the capture endpoints. sendBeacon delivery survives the page unloading under a reload.
        const url = `${host}/e/`
        if (!(typeof navigator.sendBeacon === 'function' && navigator.sendBeacon(url, payload))) {
            void fetch(url, { method: 'POST', body: payload, keepalive: true }).catch(() => {})
        }
    } catch {
        // best-effort only
    }
}

function readPersistedDistinctId(apiKey: string): string | undefined {
    try {
        // posthog-js persistence - absent on a first visit or under cookie-only persistence
        return JSON.parse(window.localStorage.getItem(`ph_${apiKey}_posthog`) || '{}').distinct_id
    } catch {
        // storage unavailable or corrupt - report anonymously
        return undefined
    }
}
