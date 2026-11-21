import { parseJSON } from '~/common/utils/json-parse'
import { aiToolCallExtractionCounter, aiToolUsageExtractionCounter } from '~/ingestion/pipelines/ai/metrics'
import { PluginEvent } from '~/plugin-scaffold'

import { extractToolCallNames, sanitizeToolName } from './extract-tool-calls'
import {
    extractDefinedToolNames,
    extractToolCallIntent,
    extractToolResults,
    findUnknownTools,
} from './extract-tool-usage'

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

export const MAX_INPUT_LENGTH = 2_000_000
const TOOL_RESULT_INDICATORS = [
    'tool_result',
    'tool-result',
    'tool_call_response',
    'function_call_output',
    'custom_tool_call_output',
    'function_call_result',
    'computer_call_output',
    'functionResponse',
    '"tool"',
    // Legacy OpenAI results use role "function".
    '"function"',
]

type Parsed = { value: unknown } | { skipped: 'too_large' | 'no_indicators' | 'invalid_json' }

function parseIfString(value: unknown, maxLength: number, indicators?: string[]): Parsed {
    if (typeof value !== 'string') {
        return { value }
    }
    if (value.length > maxLength) {
        return { skipped: 'too_large' }
    }
    if (indicators && !indicators.some((indicator) => value.includes(indicator))) {
        return { skipped: 'no_indicators' }
    }
    try {
        return { value: parseJSON(value) }
    } catch {
        return { skipped: 'invalid_json' }
    }
}

const isSet = (value: unknown): boolean => value !== undefined && value !== null

const RESULT_PROPERTIES = ['$ai_tool_result_count', '$ai_tool_error_count', '$ai_tool_results', '$ai_tool_errors']

// Runs after processAiToolCallExtraction, because unknown tools and intent read $ai_tools_called.
export function processAiToolUsageExtraction<T extends PluginEvent>(event: T): T {
    if (!event.properties || event.event !== '$ai_generation') {
        return event
    }
    const properties = event.properties

    // Any client-sent result property means the client describes its own results, so none are inferred.
    if (!RESULT_PROPERTIES.some((key) => isSet(properties[key])) && isSet(properties['$ai_input'])) {
        try {
            const input = parseIfString(properties['$ai_input'], MAX_INPUT_LENGTH, TOOL_RESULT_INDICATORS)
            if ('skipped' in input) {
                aiToolUsageExtractionCounter.labels({ kind: 'results', status: input.skipped }).inc()
            } else {
                const results = extractToolResults(input.value)
                if (results.length === 0) {
                    aiToolUsageExtractionCounter.labels({ kind: 'results', status: 'none' }).inc()
                } else {
                    const named = results.filter((result) => result.name !== null)
                    const errors = results.filter((result) => result.isError)
                    const namedErrors = named.filter((result) => result.isError)
                    properties['$ai_tool_result_count'] = results.length
                    properties['$ai_tool_error_count'] = errors.length
                    if (named.length > 0) {
                        properties['$ai_tool_results'] = named.map((result) => result.name).join(',')
                    }
                    if (namedErrors.length > 0) {
                        properties['$ai_tool_errors'] = namedErrors.map((result) => result.name).join(',')
                    }
                    aiToolUsageExtractionCounter
                        .labels({ kind: 'results', status: named.length === results.length ? 'extracted' : 'unnamed' })
                        .inc()
                }
            }
        } catch {
            aiToolUsageExtractionCounter.labels({ kind: 'results', status: 'error' }).inc()
        }
    }

    const toolsCalled = properties['$ai_tools_called']
    const called = typeof toolsCalled === 'string' ? toolsCalled.split(',').filter((name) => name.length > 0) : []
    if (called.length === 0) {
        return event
    }

    if (!isSet(properties['$ai_tools_unknown']) && isSet(properties['$ai_tools'])) {
        try {
            const tools = parseIfString(properties['$ai_tools'], MAX_INPUT_LENGTH)
            const defined = 'skipped' in tools ? null : extractDefinedToolNames(tools.value)
            if (defined === null) {
                aiToolUsageExtractionCounter.labels({ kind: 'unknown', status: 'unnamed_definitions' }).inc()
            } else {
                const unknown = findUnknownTools(called, defined)
                if (unknown.length > 0) {
                    properties['$ai_tools_unknown'] = unknown.join(',')
                }
                aiToolUsageExtractionCounter
                    .labels({ kind: 'unknown', status: unknown.length > 0 ? 'found' : 'none' })
                    .inc()
            }
        } catch {
            aiToolUsageExtractionCounter.labels({ kind: 'unknown', status: 'error' }).inc()
        }
    }

    if (!isSet(properties['$ai_tool_intent']) && isSet(properties['$ai_output_choices'])) {
        try {
            const output = parseIfString(properties['$ai_output_choices'], MAX_OUTPUT_CHOICES_LENGTH)
            const intent = 'skipped' in output ? null : extractToolCallIntent(output.value)
            if (intent !== null) {
                properties['$ai_tool_intent'] = intent
            }
            aiToolUsageExtractionCounter.labels({ kind: 'intent', status: intent !== null ? 'found' : 'none' }).inc()
        } catch {
            aiToolUsageExtractionCounter.labels({ kind: 'intent', status: 'error' }).inc()
        }
    }

    return event
}
