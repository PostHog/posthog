import { PluginEvent } from '@posthog/plugin-scaffold'

import { normalizeError } from './normalize-error'

/**
 * Process error normalization for AI events.
 *
 * Only normalizes events that have $ai_is_error = true and $ai_error property.
 * Adds $ai_error_normalized property with the normalized error message.
 *
 * This is a non-blocking operation - if normalization fails for any reason,
 * the original event is returned unchanged.
 */
export function processAiErrorNormalization(event: PluginEvent): PluginEvent {
    if (!event.properties) {
        return event
    }

    // Only process events with errors
    const isError = event.properties['$ai_is_error']
    if (isError !== true && isError !== 'true') {
        return event
    }

    const aiError = event.properties['$ai_error']
    if (aiError === undefined || aiError === null) {
        return event
    }

    // Convert to string if needed
    const errorString = typeof aiError === 'string' ? aiError : String(aiError)

    // Normalize the error message
    const normalizedError = normalizeError(errorString)

    // Only set if we have a non-empty normalized error
    if (normalizedError) {
        event.properties['$ai_error_normalized'] = normalizedError
    }

    return event
}

export { normalizeError } from './normalize-error'
