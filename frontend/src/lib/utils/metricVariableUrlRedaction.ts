import type { BeforeSendFn, CapturedNetworkRequest } from 'posthog-js'

const MARKER = 'metricVariables'
// The options requests of dashboard variables carry queries and selected values, and return query results.
const VARIABLE_OPTIONS_PATH = '/metrics/variable_options'

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

function redactProperties(properties: Record<string, any> | undefined): Record<string, any> | undefined {
    return properties && (redactValue(properties, new WeakSet()) as Record<string, any>)
}

export const redactMetricVariableUrls: BeforeSendFn = (event) =>
    event && {
        ...event,
        properties: redactProperties(event.properties) ?? event.properties,
        $set: redactProperties(event.$set),
        $set_once: redactProperties(event.$set_once),
    }

function holdsVariables(body: unknown): boolean {
    return typeof body === 'string' ? body.includes(MARKER) : !!body && JSON.stringify(body).includes(MARKER)
}

/** For session replay: a recorded request keeps its URL path only, and loses the bodies that hold metric variables. */
export function redactMetricVariableRequest(request: CapturedNetworkRequest): CapturedNetworkRequest {
    const isVariableOptions = !!request.name?.includes(VARIABLE_OPTIONS_PATH)
    return {
        ...request,
        name: request.name ? redactMetricVariableUrl(request.name) : request.name,
        requestBody: isVariableOptions || holdsVariables(request.requestBody) ? null : request.requestBody,
        responseBody: isVariableOptions || holdsVariables(request.responseBody) ? null : request.responseBody,
    }
}
