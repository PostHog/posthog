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

function extractFromToolCalls(toolCalls: unknown[]): string[] {
    const names: string[] = []
    for (const call of toolCalls) {
        if (typeof call === 'object' && call !== null) {
            const tc = call as ToolCallItem
            if (tc.function?.name && typeof tc.function.name === 'string') {
                names.push(tc.function.name)
            }
        }
    }
    return names
}

function extractFromContentBlocks(content: unknown[]): string[] {
    const names: string[] = []
    for (const block of content) {
        if (typeof block !== 'object' || block === null) {
            continue
        }
        const cb = block as ToolCallItem
        // Anthropic: {type: "tool_use", name: "..."}
        if (cb.type === 'tool_use' && cb.name && typeof cb.name === 'string') {
            names.push(cb.name)
        }
        // Normalized OpenAI: {type: "function", function: {name: "..."}}
        if (cb.type === 'function' && cb.function?.name && typeof cb.function.name === 'string') {
            names.push(cb.function.name)
        }
    }
    return names
}

// Matches ResponseFunctionToolCall(... name='tool_name' ...) from OpenAI Agents SDK Python repr
const PYTHON_REPR_TOOL_CALL_PATTERN = /ResponseFunctionToolCall\([^)]*name='([^']+)'/g

function extractFromPythonRepr(raw: string): string[] {
    const names: string[] = []
    let match
    while ((match = PYTHON_REPR_TOOL_CALL_PATTERN.exec(raw)) !== null) {
        names.push(match[1])
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
    if (!Array.isArray(outputChoices)) {
        if (rawString && typeof rawString === 'string') {
            return extractFromPythonRepr(rawString)
        }
        return []
    }

    const names: string[] = []

    for (const choice of outputChoices) {
        if (typeof choice !== 'object' || choice === null) {
            continue
        }

        const c = choice as OutputItem

        // OpenAI Responses API: flat item with {type: "function_call", name: "..."}
        if (c.type === 'function_call' && c.name && typeof c.name === 'string') {
            names.push(c.name)
            continue
        }

        // Standard OpenAI: {message: {tool_calls: [...]}}
        if (c.message && typeof c.message === 'object') {
            if ('tool_calls' in c.message && Array.isArray(c.message.tool_calls)) {
                names.push(...extractFromToolCalls(c.message.tool_calls))
            }
            if ('content' in c.message && Array.isArray(c.message.content)) {
                names.push(...extractFromContentBlocks(c.message.content))
            }
        }

        // Unwrapped: {tool_calls: [...], role: "assistant"} (no message wrapper)
        if ('tool_calls' in c && Array.isArray(c.tool_calls)) {
            names.push(...extractFromToolCalls(c.tool_calls))
        }

        // Normalized: {content: [...], role: "assistant"} (no message wrapper)
        if ('content' in c && Array.isArray(c.content)) {
            names.push(...extractFromContentBlocks(c.content))
        }
    }

    // If structured parsing found nothing, try Python repr fallback
    if (names.length === 0 && rawString && typeof rawString === 'string') {
        return extractFromPythonRepr(rawString)
    }

    return names
}
