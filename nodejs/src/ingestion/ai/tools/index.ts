import { PluginEvent } from '@posthog/plugin-scaffold'

import { parseJSON } from '../../../utils/json-parse'
import { aiToolCallExtractionCounter } from '../metrics'
import { extractToolCallNames } from './extract-tool-calls'

const TOOL_CALL_INDICATORS = ['tool_call', 'tool_use', 'function_call', '"function"', 'tool-call']
export const MAX_OUTPUT_CHOICES_LENGTH = 500_000

function stringMayContainToolCalls(s: string): boolean {
    for (const indicator of TOOL_CALL_INDICATORS) {
        if (s.includes(indicator)) {
            return true
        }
    }
    return false
}

/**
 * Extract tool call information from AI generation events.
 *
 * For $ai_generation events, parses $ai_output_choices to find tool calls
 * and sets:
 * - $ai_tools_called: comma-separated tool names in call order
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
        // Respect user-provided $ai_tools_called, but ensure $ai_tool_call_count is set
        if (event.properties['$ai_tools_called'] !== undefined && event.properties['$ai_tools_called'] !== null) {
            if (
                event.properties['$ai_tool_call_count'] === undefined ||
                event.properties['$ai_tool_call_count'] === null
            ) {
                const userTools = String(event.properties['$ai_tools_called'])
                event.properties['$ai_tool_call_count'] = userTools.split(',').filter((s) => s.trim().length > 0).length
            }
            return event
        }

        const outputChoices = event.properties['$ai_output_choices']
        if (outputChoices === undefined || outputChoices === null) {
            return event
        }

        // Keep raw string for Python repr fallback
        const rawString = typeof outputChoices === 'string' ? outputChoices : undefined

        // Fast pre-checks for string values before expensive JSON parsing
        if (typeof outputChoices === 'string') {
            if (outputChoices.length > MAX_OUTPUT_CHOICES_LENGTH) {
                aiToolCallExtractionCounter.labels({ status: 'skipped_too_large' }).inc()
                return event
            }

            if (!stringMayContainToolCalls(outputChoices)) {
                aiToolCallExtractionCounter.labels({ status: 'skipped_no_indicators' }).inc()
                return event
            }
        }

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

        event.properties['$ai_tools_called'] = toolNames.join(',')
        event.properties['$ai_tool_call_count'] = toolNames.length
        aiToolCallExtractionCounter.labels({ status: 'extracted' }).inc()

        return event
    } catch {
        aiToolCallExtractionCounter.labels({ status: 'error' }).inc()
        return event
    }
}
