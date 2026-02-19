import { PluginEvent } from '@posthog/plugin-scaffold'

import { parseJSON } from '../../../utils/json-parse'
import { aiToolCallExtractionCounter } from '../metrics'
import { extractToolCallNames } from './extract-tool-calls'

/**
 * Extract tool call information from AI generation events.
 *
 * For $ai_generation events, parses $ai_output_choices to find tool calls
 * and sets:
 * - $ai_tools_called: JSON array of tool names in call order
 * - $ai_tool_call_count: integer count of tool calls
 *
 * Respects user-provided values (same pattern as error normalization).
 */
export function processAiToolCallExtraction<T extends PluginEvent>(event: T): T {
    if (!event.properties) {
        return event
    }

    // Only process $ai_generation events
    if (event.event !== '$ai_generation') {
        return event
    }

    try {
        // Respect user-provided values
        if (event.properties['$ai_tools_called'] !== undefined && event.properties['$ai_tools_called'] !== null) {
            return event
        }

        const outputChoices = event.properties['$ai_output_choices']
        if (outputChoices === undefined || outputChoices === null) {
            return event
        }

        // Keep raw string for Python repr fallback
        const rawString = typeof outputChoices === 'string' ? outputChoices : undefined

        // Parse if string
        let parsed: unknown = outputChoices
        if (typeof outputChoices === 'string') {
            try {
                parsed = parseJSON(outputChoices)
            } catch {
                // Not valid JSON - pass through for Python repr fallback
                parsed = undefined
            }
        }

        const toolNames = extractToolCallNames(parsed, rawString)

        if (toolNames.length === 0) {
            return event
        }

        event.properties['$ai_tools_called'] = JSON.stringify(toolNames)
        event.properties['$ai_tool_call_count'] = toolNames.length
        aiToolCallExtractionCounter.labels({ status: 'extracted' }).inc()

        return event
    } catch {
        aiToolCallExtractionCounter.labels({ status: 'error' }).inc()
        return event
    }
}
