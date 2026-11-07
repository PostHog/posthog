import type { BeforeSendFn } from 'posthog-js'

const MARKERS = ['metricVariables', 'bi_filter']
const URL_START = String.raw`(?:^|[\s"'(])` // Bounds repeated-link scans to linear time.
const URL_HOST = String.raw`(?:(?:https?:)?\/\/[^/?#\s"'<>(]+)?`
const LOGIN_URL_WITH_PARAMS = new RegExp(String.raw`${URL_START}${URL_HOST}\/login(?:\/[^?#\s"'<>(]*)?[?#]`, 'i')
const TOKEN_URL = new RegExp(
    String.raw`${URL_START}(${URL_HOST}\/(?:reset|reset_2fa|verify_email))\/[^/?#\s"'<>(]+\/[^?#\s"'<>(]+`,
    'i'
)
// The options requests of dashboard variables carry queries and selected values, and return query results.
const VARIABLE_OPTIONS_PATH = '/metrics/variable_options'
const NETWORK_PLUGIN = 'rrweb/network@1'

function holdsFilterData(text: string): boolean {
    return MARKERS.some((marker) => text.includes(marker))
}

/** Keeps only paths for URLs containing sensitive analytics values or one-time login tokens; drops matching non-URL text. */
export function redactMetricVariableUrl(text: string): string {
    if (!holdsFilterData(text) && !LOGIN_URL_WITH_PARAMS.test(text) && !TOKEN_URL.test(text)) {
        return text
    }
    if (text.startsWith('/') || /^https?:\/\/\S+$/.test(text)) {
        return text.split(/[?#]/)[0].replace(TOKEN_URL, '$1')
    }
    return ''
}

function isObject(value: unknown): value is object {
    return value !== null && typeof value === 'object'
}

/** Every string at any depth, such as `$current_url`, an autocaptured `href`, or a request in a replay snapshot.
 * A value with nothing to redact is returned as it is, so a large snapshot is not copied. */
function redactValue(value: unknown, seen: WeakMap<object, object>): unknown {
    if (typeof value === 'string') {
        return redactMetricVariableUrl(value)
    }
    if (!isObject(value)) {
        return value
    }
    const existing = seen.get(value)
    if (existing) {
        return existing
    }
    seen.set(value, value)
    if (Array.isArray(value)) {
        let copy: unknown[] | null = null
        value.forEach((item, index) => {
            const redacted = redactValue(item, seen)
            if (redacted !== item) {
                copy ??= [...value]
                copy[index] = redacted
            }
        })
        const result = copy ?? value
        seen.set(value, result)
        return result
    }
    let copy: Record<string, unknown> | null = null
    for (const [key, item] of Object.entries(value)) {
        const redacted = redactValue(item, seen)
        if (redacted !== item) {
            copy ??= { ...value }
            copy[key] = redacted
        }
    }
    const result = copy ?? value
    seen.set(value, result)
    return result
}

function holdsVariableData(request: unknown): boolean {
    if (!request || typeof request !== 'object') {
        return false
    }
    const { name, requestBody, responseBody } = request as Record<string, unknown>
    return (
        (typeof name === 'string' && (name.includes(VARIABLE_OPTIONS_PATH) || holdsFilterData(name))) ||
        [requestBody, responseBody].some((body) => typeof body === 'string' && holdsFilterData(body))
    )
}

/** Replay records network requests in snapshots. The ones that carry metric variable data are left out, and the
 * SDK's own body scrubbing still applies to the rest. */
function withoutVariableRequests(snapshots: unknown): unknown {
    if (!Array.isArray(snapshots)) {
        return snapshots
    }
    let copy: unknown[] | null = null
    snapshots.forEach((snapshot, index) => {
        const data = snapshot?.data
        const requests = data?.plugin === NETWORK_PLUGIN ? data.payload?.requests : undefined
        if (!Array.isArray(requests) || !requests.some(holdsVariableData)) {
            return
        }
        copy ??= [...snapshots]
        const kept = requests.filter((request) => !holdsVariableData(request))
        copy[index] = { ...snapshot, data: { ...data, payload: { ...data.payload, requests: kept } } }
    })
    return copy ?? snapshots
}

function redactProperties(properties: Record<string, any> | undefined): Record<string, any> | undefined {
    if (!properties) {
        return properties
    }
    const snapshots = properties.$snapshot_data
    const filtered = withoutVariableRequests(snapshots)
    const base = filtered === snapshots ? properties : { ...properties, $snapshot_data: filtered }
    return redactValue(base, new WeakMap()) as Record<string, any>
}

export const redactMetricVariableUrls: BeforeSendFn = (event) =>
    event && {
        ...event,
        properties: redactProperties(event.properties) ?? event.properties,
        $set: redactProperties(event.$set),
        $set_once: redactProperties(event.$set_once),
    }
