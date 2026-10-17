import type { BeforeSendFn } from 'posthog-js'

const URL_PROPERTIES = ['$current_url', '$referrer', '$initial_current_url', '$initial_referrer']
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

function redactProperties(properties: Record<string, any> | undefined): Record<string, any> | undefined {
    if (!properties || !URL_PROPERTIES.some((key) => typeof properties[key] === 'string')) {
        return properties
    }
    const redacted = { ...properties }
    for (const key of URL_PROPERTIES) {
        if (typeof redacted[key] === 'string') {
            redacted[key] = redactMetricVariableUrl(redacted[key])
        }
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
