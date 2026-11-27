import type { BeforeSendFn } from 'posthog-js'

import { redactStrings } from './metricVariableUrlRedaction'

// AI observability pages and API paths carry customer text in these params: error messages, tool names, keys that
// encode them, property filters and searches. A URL inside another URL's param percent-encodes the separators.
const CUSTOMER_TEXT_PARAM =
    /((?:[?&#]|%(?:25)?(?:3F|26|23))(?:error|tool|failed_tool|filters|\w*search)(?:=|%(?:25)?3D))[^&#"'\s]*/gi

export function redactAIObservabilityUrl(text: string): string {
    return /ai[-_]observability/i.test(text) ? text.replace(CUSTOMER_TEXT_PARAM, '$1redacted') : text
}

/** Covers `$current_url` on every event, autocaptured links, and the page and request URLs that replay records. */
export const redactAIObservabilityUrls: BeforeSendFn = (event) =>
    event && {
        ...event,
        properties: redactStrings(event.properties, redactAIObservabilityUrl),
        $set: redactStrings(event.$set, redactAIObservabilityUrl),
        $set_once: redactStrings(event.$set_once, redactAIObservabilityUrl),
    }
