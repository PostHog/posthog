/**
 * Main orchestrator for AI event processing.
 *
 * This module coordinates all AI event enrichment:
 * - Trace property normalization (for all AI events)
 * - Error normalization (for AI events with errors)
 * - Cost calculation (for generation/embedding events)
 * - Model parameter extraction (for generation/embedding events)
 */
import { PluginEvent } from '@posthog/plugin-scaffold'

import { logger } from '../../utils/logger'
import { EventWithProperties, extractCoreModelParams, processCost } from './costs'
import { processAiErrorNormalization } from './errors'

export { EventWithProperties } from './costs'

const isEventWithProperties = (event: PluginEvent): event is EventWithProperties => {
    return event.properties !== undefined && event.properties !== null
}

export const AI_EVENT_TYPES = new Set([
    '$ai_generation',
    '$ai_embedding',
    '$ai_span',
    '$ai_trace',
    '$ai_metric',
    '$ai_feedback',
])

/**
 * Process an AI event through the enrichment pipeline.
 *
 * Pipeline steps:
 * 1. Normalize trace properties (all AI events)
 * 2. Normalize error messages (events with $ai_is_error=true)
 * 3. Calculate costs (generation/embedding events only)
 * 4. Extract model parameters (generation/embedding events only)
 */
export const processAiEvent = (event: PluginEvent): PluginEvent | EventWithProperties => {
    // If the event doesn't carry properties, there's nothing to do.
    if (!isEventWithProperties(event)) {
        return event
    }

    // Normalize trace properties for all AI events.
    const normalized: EventWithProperties = AI_EVENT_TYPES.has(event.event) ? normalizeTraceProperties(event) : event

    // Normalize error messages for all AI events with errors.
    const withErrorNormalization = processAiErrorNormalization(normalized) as EventWithProperties

    // Only generation/embedding events get cost processing and model param extraction.
    const isCosted =
        withErrorNormalization.event === '$ai_generation' || withErrorNormalization.event === '$ai_embedding'

    if (!isCosted) {
        return withErrorNormalization
    }

    const eventWithCosts = processCost(withErrorNormalization)

    return extractCoreModelParams(eventWithCosts)
}

/**
 * Normalize trace properties to ensure they are strings.
 * Handles conversion of numbers, booleans, and bigints to strings.
 */
export const normalizeTraceProperties = (event: EventWithProperties): EventWithProperties => {
    const keys = ['$ai_trace_id', '$ai_parent_id', '$ai_span_id', '$ai_generation_id', '$ai_session_id']

    for (const key of keys) {
        const value: unknown = event.properties[key]

        if (value === null || value === undefined) {
            continue
        }

        const valueType = typeof value

        if (valueType === 'string' || valueType === 'number' || valueType === 'boolean' || valueType === 'bigint') {
            event.properties[key] = String(value)
        } else {
            event.properties[key] = undefined

            logger.warn(`Unexpected type for trace property ${key}: ${valueType}`)
        }
    }

    return event
}
