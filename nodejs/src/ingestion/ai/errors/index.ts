import { PluginEvent } from '@posthog/plugin-scaffold'

import { aiErrorNormalizationCounter } from '../metrics'
import { normalizeError } from './normalize-error'

const UNKNOWN_ERROR = 'Unknown error'

/**
 * Process error normalization for AI events.
 *
 * For all events with $ai_is_error = true, ensures $ai_error_normalized is set.
 * This guarantees errors can be grouped in the LLM analytics errors tab.
 *
 * This is a non-blocking operation - if normalization fails for any reason,
 * a fallback value is used.
 */
export function processAiErrorNormalization<T extends PluginEvent>(event: T): T {
    if (!event.properties) {
        return event
    }

    try {
        // Only process events with errors
        const isError = event.properties['$ai_is_error']
        if (isError !== true && isError !== 'true') {
            return event
        }

        // Respect user-provided normalized error
        if (event.properties['$ai_error_normalized']) {
            return event
        }

        const aiError = event.properties['$ai_error']
        if (aiError === undefined || aiError === null) {
            // No error message provided, use fallback
            event.properties['$ai_error_normalized'] = UNKNOWN_ERROR
            aiErrorNormalizationCounter.labels({ status: 'fallback' }).inc()
            return event
        }

        // Convert to string if needed
        let errorString: string
        if (typeof aiError === 'string') {
            errorString = aiError
        } else {
            try {
                errorString = JSON.stringify(aiError)
            } catch {
                errorString = String(aiError)
            }
        }

        // Normalize the error message
        const normalizedError = normalizeError(errorString)

        // Always set normalized error, use fallback if normalization produced empty result
        event.properties['$ai_error_normalized'] = normalizedError || UNKNOWN_ERROR
        aiErrorNormalizationCounter.labels({ status: normalizedError ? 'normalized' : 'fallback' }).inc()

        return event
    } catch {
        // Ensure we still set a value even on error
        event.properties['$ai_error_normalized'] = UNKNOWN_ERROR
        aiErrorNormalizationCounter.labels({ status: 'error' }).inc()
        return event
    }
}

export { normalizeError } from './normalize-error'
