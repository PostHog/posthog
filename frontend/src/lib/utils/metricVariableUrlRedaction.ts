import type { BeforeSendFn } from 'posthog-js'

const MARKER = 'metricVariables'
// The options requests of dashboard variables carry queries and selected values, and return query results.
const VARIABLE_OPTIONS_PATH = '/metrics/variable_options'
const NETWORK_PLUGIN = 'rrweb/network@1'

/** A URL that holds metric variables, in any parameter or encoding, keeps only its path, so the queries, options and
 * selected values of the variables stay out of analytics. Other text that holds them is dropped. */
export function redactMetricVariableUrl(text: string): string {
    if (!text.includes(MARKER)) {
        return text
    }
    if (text.startsWith('/') || /^https?:\/\/\S+$/.test(text)) {
        return text.split(/[?#]/)[0]
    }
    return ''
}

/** Every string at any depth, such as `$current_url`, an autocaptured `href`, or a request in a replay snapshot.
 * A value with nothing to redact is returned as it is, so a large snapshot is not copied. */
function redactValue(value: unknown, seen: WeakSet<object>): unknown {
    if (typeof value === 'string') {
        return redactMetricVariableUrl(value)
    }
    if (!value || typeof value !== 'object' || seen.has(value)) {
        return value
    }
    seen.add(value)
    if (Array.isArray(value)) {
        let copy: unknown[] | null = null
        value.forEach((item, index) => {
            const redacted = redactValue(item, seen)
            if (redacted !== item) {
                copy ??= [...value]
                copy[index] = redacted
            }
        })
        return copy ?? value
    }
    let copy: Record<string, unknown> | null = null
    for (const [key, item] of Object.entries(value)) {
        const redacted = redactValue(item, seen)
        if (redacted !== item) {
            copy ??= { ...value }
            copy[key] = redacted
        }
    }
    return copy ?? value
}

function holdsVariableData(request: unknown): boolean {
    if (!request || typeof request !== 'object') {
        return false
    }
    const { name, requestBody, responseBody } = request as Record<string, unknown>
    return (
        (typeof name === 'string' && (name.includes(VARIABLE_OPTIONS_PATH) || name.includes(MARKER))) ||
        [requestBody, responseBody].some((body) => typeof body === 'string' && body.includes(MARKER))
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
    return redactValue(base, new WeakSet()) as Record<string, any>
}

export const redactMetricVariableUrls: BeforeSendFn = (event) =>
    event && {
        ...event,
        properties: redactProperties(event.properties) ?? event.properties,
        $set: redactProperties(event.$set),
        $set_once: redactProperties(event.$set_once),
    }
