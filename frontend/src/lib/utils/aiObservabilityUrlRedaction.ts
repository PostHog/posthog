import type { BeforeSendFn } from 'posthog-js'

import { redactStrings } from './metricVariableUrlRedaction'

const REDACTED = 'redacted'
// The app's pages and its API both name the product, with a hyphen and with an underscore.
const AI_OBSERVABILITY_PATH = /ai[-_]observability/i
// Each of these parameters carries customer text: an error message, a tool name, a key that encodes one of them, or
// a search for such text. The separator may be percent-encoded once or twice, when the URL is a parameter of another
// URL, such as a login redirect.
const CUSTOMER_TEXT_PARAM =
    /((?:[?&#]|%(?:25)?(?:3F|26|23))(?:error|tool|failed_tool|search|error_search|tool_search|trace_search)(?:=|%(?:25)?3D))[^&#"'\s]*/gi

/** Replaces the values of the customer text parameters in a URL of AI observability, anywhere in the text. */
export function redactAIObservabilityUrl(text: string): string {
    if (!AI_OBSERVABILITY_PATH.test(text)) {
        return text
    }
    return text.replace(CUSTOMER_TEXT_PARAM, `$1${REDACTED}`)
}

/** Covers `$current_url` on every event, autocaptured links, and the page and request URLs that replay records. */
export const redactAIObservabilityUrls: BeforeSendFn = (event) =>
    event && {
        ...event,
        properties: redactStrings(event.properties, redactAIObservabilityUrl),
        $set: redactStrings(event.$set, redactAIObservabilityUrl),
        $set_once: redactStrings(event.$set_once, redactAIObservabilityUrl),
    }
