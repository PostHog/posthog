/**
 * Extract tool call names from AI generation output choices.
 *
 * Handles multiple formats:
 * - OpenAI Chat: `choices[].message.tool_calls[].function.name`
 * - OpenAI Chat (unwrapped): `[].tool_calls[].function.name` (no message wrapper)
 * - OpenAI Responses API: flat `[].type="function_call"` with `name` at top level
 * - Normalized SDK: `[].content[].type="function"` with `function.name`
 * - Anthropic: `[].message.content[].type="tool_use"` with `name`
 * - Python repr (OpenAI Agents SDK): `ResponseFunctionToolCall(name='...')`
 */

export const MAX_TOOL_NAME_LENGTH = 200
export const MAX_TOOLS_PER_EVENT = 100

interface ToolCallItem {
    type?: string
    name?: string
    function?: {
        name?: string
    }
}

interface OutputItem {
    type?: string
    name?: string
    role?: string
    content?: ToolCallItem[]
    tool_calls?: ToolCallItem[]
    message?: {
        tool_calls?: ToolCallItem[]
        content?: ToolCallItem[]
    }
}

export function sanitizeToolName(name: string): string | null {
    let sanitized = name.trim()
    if (sanitized.length === 0) {
        return null
    }
    sanitized = sanitized.replace(/,/g, '_')
    if (sanitized.length > MAX_TOOL_NAME_LENGTH) {
        sanitized = sanitized.slice(0, MAX_TOOL_NAME_LENGTH)
    }
    return sanitized
}

function pushSanitized(names: string[], raw: string): void {
    const sanitized = sanitizeToolName(raw)
    if (sanitized !== null) {
        names.push(sanitized)
    }
}

function extractFromToolCalls(toolCalls: unknown[], names: string[], cap: number): void {
    for (const call of toolCalls) {
        if (names.length >= cap) {
            return
        }
        if (typeof call === 'object' && call !== null) {
            const tc = call as ToolCallItem
            if (tc.function?.name && typeof tc.function.name === 'string') {
                pushSanitized(names, tc.function.name)
            }
        }
    }
}

function extractFromContentBlocks(content: unknown[], names: string[], cap: number): void {
    for (const block of content) {
        if (names.length >= cap) {
            return
        }
        if (typeof block !== 'object' || block === null) {
            continue
        }
        const cb = block as ToolCallItem
        // Anthropic: {type: "tool_use", name: "..."}
        if (cb.type === 'tool_use' && cb.name && typeof cb.name === 'string') {
            pushSanitized(names, cb.name)
        }
        // Normalized OpenAI: {type: "function", function: {name: "..."}}
        else if (cb.type === 'function' && cb.function?.name && typeof cb.function.name === 'string') {
            pushSanitized(names, cb.function.name)
        }
    }
}

// Matches ResponseFunctionToolCall(... name='tool_name' ...) from OpenAI Agents SDK Python repr
const PYTHON_REPR_TOOL_CALL_PATTERN = /ResponseFunctionToolCall\([^)]*name='([^']+)'/g

function extractFromPythonRepr(raw: string): string[] {
    const names: string[] = []
    let match
    while ((match = PYTHON_REPR_TOOL_CALL_PATTERN.exec(raw)) !== null) {
        if (names.length >= MAX_TOOLS_PER_EVENT) {
            break
        }
        pushSanitized(names, match[1])
    }
    // Reset lastIndex for stateful regex
    PYTHON_REPR_TOOL_CALL_PATTERN.lastIndex = 0
    return names
}

/**
 * Extract tool call names from output choices in call order.
 * Returns an empty array if no tool calls are found or data is malformed.
 *
 * Also accepts a raw string for Python repr format fallback.
 */
export function extractToolCallNames(outputChoices: unknown, rawString?: string): string[] {
    // Unwrap {"choices": [...]} wrapper (some SDKs store full API response)
    if (
        typeof outputChoices === 'object' &&
        outputChoices !== null &&
        !Array.isArray(outputChoices) &&
        'choices' in outputChoices &&
        Array.isArray((outputChoices as Record<string, unknown>).choices)
    ) {
        outputChoices = (outputChoices as Record<string, unknown>).choices
    }

    if (!Array.isArray(outputChoices)) {
        if (rawString && typeof rawString === 'string') {
            return extractFromPythonRepr(rawString)
        }
        return []
    }

    const names: string[] = []

    for (const choice of outputChoices) {
        if (names.length >= MAX_TOOLS_PER_EVENT) {
            break
        }

        if (typeof choice !== 'object' || choice === null) {
            continue
        }

        const c = choice as OutputItem

        // OpenAI Responses API: flat item with {type: "function_call", name: "..."}
        if (c.type === 'function_call' && c.name && typeof c.name === 'string') {
            pushSanitized(names, c.name)
            continue
        }

        // Standard OpenAI / Anthropic: {message: {tool_calls: [...], content: [...]}}
        if (c.message && typeof c.message === 'object') {
            if ('tool_calls' in c.message && Array.isArray(c.message.tool_calls)) {
                extractFromToolCalls(c.message.tool_calls, names, MAX_TOOLS_PER_EVENT)
            }
            if ('content' in c.message && Array.isArray(c.message.content)) {
                extractFromContentBlocks(c.message.content, names, MAX_TOOLS_PER_EVENT)
            }
        } else {
            // Unwrapped: {tool_calls: [...], role: "assistant"} (no message wrapper)
            if ('tool_calls' in c && Array.isArray(c.tool_calls)) {
                extractFromToolCalls(c.tool_calls, names, MAX_TOOLS_PER_EVENT)
            }

            // Normalized: {content: [...], role: "assistant"} (no message wrapper)
            if ('content' in c && Array.isArray(c.content)) {
                extractFromContentBlocks(c.content, names, MAX_TOOLS_PER_EVENT)
            }
        }
    }

    // If structured parsing found nothing, try Python repr fallback
    if (names.length === 0 && rawString && typeof rawString === 'string') {
        return extractFromPythonRepr(rawString)
    }

    return names
}
