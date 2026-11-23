import { isChunkLoadError } from 'lib/utils/isChunkLoadError'
import { redactMetricVariableUrl } from 'lib/utils/metricVariableUrlRedaction'

function getDistinctId(apiKey: string): string | undefined {
    let distinctId: string | undefined
    try {
        // posthog-js persistence — absent on a first visit or under cookie-only persistence
        distinctId = JSON.parse(window.localStorage.getItem(`ph_${apiKey}_posthog`) || '{}').distinct_id
    } catch {
        // storage unavailable or corrupt — report anonymously
    }
    return distinctId
}

function sendBootFailure(host: string, payload: string): void {
    // A string body goes out as text/plain: CORS-safelisted (no preflight) and accepted by
    // the capture endpoints. sendBeacon delivery survives the page unloading under a reload.
    const url = `${host}/e/`
    if (!(typeof navigator.sendBeacon === 'function' && navigator.sendBeacon(url, payload))) {
        void fetch(url, { method: 'POST', body: payload, keepalive: true }).catch(() => {})
    }
}

/**
 * Report a boot failure straight to the capture API. posthog-js lives inside the App chunk —
 * the very chunk this boundary guards — so when boot fails there is no SDK to report through,
 * and without this beacon a broken deploy would be invisible to error tracking.
 * Fire-and-forget: reporting must never make a boot failure worse.
 */
export function reportBootFailure(error: unknown): void {
    try {
        const apiKey = window.JS_POSTHOG_API_KEY
        if (!apiKey || window.IMPERSONATED_SESSION) {
            return // capture is opted out for this instance
        }
        const host = window.JS_POSTHOG_HOST || window.location.origin
        const err = error instanceof Error ? error : new Error(String(error))
        const payload = JSON.stringify({
            api_key: apiKey,
            event: '$exception',
            distinct_id: getDistinctId(apiKey) || `boot-failure-${Date.now()}`,
            properties: {
                // Personless event: don't create person profiles from anonymous boot beacons
                $process_person_profile: false,
                $current_url: redactMetricVariableUrl(window.location.href),
                $exception_level: 'fatal',
                $exception_list: [
                    {
                        type: err.name || 'Error',
                        value: err.message,
                        mechanism: { handled: true, synthetic: false },
                    },
                ],
                stack: err.stack,
                chunk_load_error: isChunkLoadError(error),
            },
        })
        sendBootFailure(host, payload)
    } catch {
        // best-effort only
    }
}
