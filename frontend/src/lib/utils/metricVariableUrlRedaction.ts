import type { BeforeSendFn } from 'posthog-js'

const MAX_DEPTH = 6

/** A URL that holds metric variables, in any parameter or encoding, keeps only its path, so the queries, options and
 * selected values of the variables stay out of analytics. Other text that holds them is dropped. */
export function redactMetricVariableUrl(text: string): string {
    if (!text.includes('metricVariables')) {
        return text
    }
    if (text.startsWith('/') || /^https?:\/\/\S+$/.test(text)) {
        return text.split(/[?#]/)[0]
    }
    return ''
}

/** Every property, such as `$current_url`, `$session_entry_url` or the `href` of an autocaptured element, so a new
 * one in the SDK is covered too. */
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
