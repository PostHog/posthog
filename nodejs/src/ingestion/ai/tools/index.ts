import { PluginEvent } from '~/plugin-scaffold'

import { parseJSON } from '../../../utils/json-parse'
import { aiToolCallExtractionCounter } from '../metrics'
import { extractToolCallNames, sanitizeToolName } from './extract-tool-calls'

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
 * Normalize a user-provided $ai_tools_called value to a comma-separated string.
 *
 * Downstream queries (e.g. the Tools view) assume a comma-separated string and
 * render via splitByChar(','). Users often send an array or a JSON-stringified
 * array instead, which caused tool names to render with JSON punctuation.
 *
 * Returns null if the value cannot be coerced into a usable string.
 */
function normalizeUserProvidedToolsCalled(value: unknown): string | null {
    let names: unknown[] | null = null

    if (Array.isArray(value)) {
        names = value
    } else if (typeof value === 'string') {
        const trimmed = value.trim()
        if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
            try {
                const parsed = parseJSON(trimmed)
                if (Array.isArray(parsed)) {
                    names = parsed
                }
            } catch {
                // Fall through to treat as a plain string
            }
        }
        if (names === null) {
            // Treat empty / whitespace-only strings the same as empty arrays.
            return value.trim().length > 0 ? value : null
        }
    } else {
        return String(value)
    }

    const sanitized: string[] = []
    for (const name of names) {
        if (typeof name !== 'string') {
            continue
        }
        const clean = sanitizeToolName(name)
        if (clean !== null) {
            sanitized.push(clean)
        }
    }
    return sanitized.length > 0 ? sanitized.join(',') : null
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
        // Respect user-provided $ai_tools_called, but normalize array / JSON-stringified array
        // shapes into the comma-separated string that downstream queries expect, and ensure
        // $ai_tool_call_count is set.
        if (event.properties['$ai_tools_called'] !== undefined && event.properties['$ai_tools_called'] !== null) {
            const normalized = normalizeUserProvidedToolsCalled(event.properties['$ai_tools_called'])
            if (normalized === null) {
                delete event.properties['$ai_tools_called']
                aiToolCallExtractionCounter.labels({ status: 'user_provided_invalid' }).inc()
                return event
            }
            event.properties['$ai_tools_called'] = normalized
            if (
                event.properties['$ai_tool_call_count'] === undefined ||
                event.properties['$ai_tool_call_count'] === null
            ) {
                event.properties['$ai_tool_call_count'] = normalized
                    .split(',')
                    .filter((s) => s.trim().length > 0).length
            }
            aiToolCallExtractionCounter.labels({ status: 'user_provided' }).inc()
            return event
        }

        const outputChoices = event.properties['$ai_output_choices']
        if (outputChoices === undefined || outputChoices === null) {
            aiToolCallExtractionCounter.labels({ status: 'no_output_choices' }).inc()
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
            aiToolCallExtractionCounter.labels({ status: 'no_tools_found' }).inc()
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
