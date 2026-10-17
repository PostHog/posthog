import type { BeforeSendFn } from 'posthog-js'

// The value of a dashboard filter parameter in a URL, wherever the URL appears in the text.
const FILTER_PARAM = /\b(filters_override|query_filters)=([^&#"'\s;]*)/g
const MAX_DEPTH = 6

function redactFilters(encoded: string): string {
    try {
        const filters = JSON.parse(decodeURIComponent(encoded.replace(/\+/g, ' ')))
        if (!Array.isArray(filters?.metricVariables)) {
            return encoded
        }
        filters.metricVariables = filters.metricVariables.map((variable: Record<string, unknown> | null) => ({
            name: variable?.name,
        }))
        return encodeURIComponent(JSON.stringify(filters))
    } catch {
        return ''
    }
}

/** Metric variables in a dashboard or insight URL keep only their names, so their queries, options and selected values
 * stay out of analytics. The text can be a URL or hold one, such as an element chain. */
export function redactMetricVariableUrl(text: string): string {
    if (!text.includes('metricVariables')) {
        return text
    }
    return text.replace(FILTER_PARAM, (match, param: string, value: string) =>
        value.includes('metricVariables') ? `${param}=${redactFilters(value)}` : match
    )
}

/** Every property that holds a URL, such as `$current_url`, `$session_entry_url` or the `href` of an autocaptured
 * element, so a new one in the SDK is covered too. */
function redactValue(value: unknown, depth: number): unknown {
    if (typeof value === 'string') {
        return redactMetricVariableUrl(value)
    }
    if (depth >= MAX_DEPTH || !value || typeof value !== 'object') {
        return value
    }
    if (Array.isArray(value)) {
        return value.map((item) => redactValue(item, depth + 1))
    }
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, redactValue(item, depth + 1)]))
}

function redactProperties(properties: Record<string, any> | undefined): Record<string, any> | undefined {
    if (!properties || !JSON.stringify(properties).includes('metricVariables')) {
        return properties
    }
    return redactValue(properties, 0) as Record<string, any>
}

export const redactMetricVariableUrls: BeforeSendFn = (event) =>
    event && {
        ...event,
        properties: redactProperties(event.properties) ?? event.properties,
        $set: redactProperties(event.$set),
        $set_once: redactProperties(event.$set_once),
    }
