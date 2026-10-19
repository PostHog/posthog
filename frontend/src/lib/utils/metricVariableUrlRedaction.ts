import type { BeforeSendFn } from 'posthog-js'

const FILTER_PARAMS = ['filters_override', 'query_filters']

/** Metric variables in a dashboard or insight URL keep only their names, so their queries, options and selected values
 * stay out of analytics. */
export function redactMetricVariableUrl(url: string): string {
    if (!url.includes('metricVariables')) {
        return url
    }
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        return url
    }
    for (const param of FILTER_PARAMS) {
        const raw = parsed.searchParams.get(param)
        if (!raw?.includes('metricVariables')) {
            continue
        }
        try {
            const filters = JSON.parse(raw)
            if (Array.isArray(filters?.metricVariables)) {
                filters.metricVariables = filters.metricVariables.map((variable: Record<string, unknown> | null) => ({
                    name: variable?.name,
                }))
                parsed.searchParams.set(param, JSON.stringify(filters))
            }
        } catch {
            parsed.searchParams.delete(param)
        }
    }
    return parsed.toString()
}

/** Every URL property, such as `$current_url` or `$session_entry_url`, so a new one in the SDK is covered too. */
function redactProperties(properties: Record<string, any> | undefined): Record<string, any> | undefined {
    const keys = Object.keys(properties ?? {}).filter(
        (key) => typeof properties![key] === 'string' && properties![key].includes('metricVariables')
    )
    if (!properties || !keys.length) {
        return properties
    }
    const redacted = { ...properties }
    for (const key of keys) {
        redacted[key] = redactMetricVariableUrl(redacted[key])
    }
    return redacted
}

export const redactMetricVariableUrls: BeforeSendFn = (event) =>
    event && {
        ...event,
        properties: redactProperties(event.properties) ?? event.properties,
        $set: redactProperties(event.$set),
        $set_once: redactProperties(event.$set_once),
    }
