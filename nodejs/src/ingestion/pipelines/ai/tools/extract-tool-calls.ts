/**
 * Extract tool call names from AI generation output choices.
 *
 * Handles multiple formats:
 * - OpenAI Chat: `choices[].message.tool_calls[].function.name`
 * - OpenAI Chat (unwrapped): `[].tool_calls[].function.name` (no message wrapper)
 * - OpenAI Responses API: flat `[].type="function_call"` with `name` at top level
 * - Normalized SDK: `[].content[].type="function"` with `function.name`
 * - Vercel AI SDK / OTel: `[].content[].type="tool-call"` with `function.name` or `toolName`
 * - Pydantic AI OTel: `[].parts[].type="tool_call"` with `name`
 * - Anthropic: `[].message.content[].type="tool_use"` with `name`
 * - Gemini: `[].parts[].functionCall` with `name`
 * - Python repr (OpenAI Agents SDK): `ResponseFunctionToolCall(name='...')`
 */

export const MAX_TOOL_NAME_LENGTH = 200
export const MAX_TOOLS_PER_EVENT = 100

interface OutputItem {
    type?: string
    name?: string
    role?: string
    content?: unknown[]
    parts?: unknown[]
    tool_calls?: unknown[]
    message?: {
        tool_calls?: unknown[]
        content?: unknown[]
        parts?: unknown[]
    }
}

export interface ToolCallRef {
    id: string | undefined
    name: string | undefined
}

type Item = Record<string, unknown>

const isObject = (value: unknown): value is Item => typeof value === 'object' && value !== null && !Array.isArray(value)

const asString = (value: unknown): string | undefined =>
    typeof value === 'string' && value.length > 0 ? value : undefined

const FLAT_CALL_TYPES = new Set(['function_call', 'custom_tool_call', 'computer_call'])
const CALL_PART_TYPES = new Set(['tool_use', 'tool-call', 'tool_call', 'function'])

// OpenAI Responses: a flat input or output item, e.g. {type: "function_call", call_id: "...", name: "..."}.
export function readFlatToolCall(item: unknown): ToolCallRef | null {
    if (!isObject(item) || typeof item.type !== 'string' || !FLAT_CALL_TYPES.has(item.type)) {
        return null
    }
    return { id: asString(item.call_id ?? item.callId ?? item.id), name: asString(item.name) }
}

// A message part or a `tool_calls` entry. Call ids and names are read here for every provider
// format, so extracted calls and the calls that tool results point back to cannot disagree.
export function readToolCall(part: unknown): ToolCallRef | null {
    if (!isObject(part)) {
        return null
    }
    // Gemini parts have no type: {functionCall: {id, name, args}}
    if (isObject(part.functionCall)) {
        return { id: asString(part.functionCall.id), name: asString(part.functionCall.name) }
    }
    const isCallPart = typeof part.type === 'string' && CALL_PART_TYPES.has(part.type)
    if (!isCallPart && !isObject(part.function)) {
        return null
    }
    const call = isObject(part.toolInvoke) ? part.toolInvoke : part
    return {
        id: asString(call.id ?? call.toolCallId ?? call.tool_call_id),
        name: asString(isObject(call.function) ? call.function.name : (call.name ?? call.toolName)),
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

function extractFromCalls(calls: unknown[], names: string[]): void {
    for (const call of calls) {
        if (names.length >= MAX_TOOLS_PER_EVENT) {
            return
        }
        const name = readToolCall(call)?.name
        if (name) {
            pushSanitized(names, name)
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
        const flatCall = readFlatToolCall(c)
        if (flatCall) {
            if (flatCall.name) {
                pushSanitized(names, flatCall.name)
            }
            continue
        }

        // Standard OpenAI / Anthropic: {message: {tool_calls: [...], content: [...]}}
        if (c.message && typeof c.message === 'object') {
            if ('tool_calls' in c.message && Array.isArray(c.message.tool_calls)) {
                extractFromCalls(c.message.tool_calls, names)
            }
            if ('content' in c.message && Array.isArray(c.message.content)) {
                extractFromCalls(c.message.content, names)
            }
            if ('parts' in c.message && Array.isArray(c.message.parts)) {
                extractFromCalls(c.message.parts, names)
            }
        } else {
            // Unwrapped: {tool_calls: [...], role: "assistant"} (no message wrapper)
            if ('tool_calls' in c && Array.isArray(c.tool_calls)) {
                extractFromCalls(c.tool_calls, names)
            }

            // Normalized: {content: [...], role: "assistant"} (no message wrapper)
            if ('content' in c && Array.isArray(c.content)) {
                extractFromCalls(c.content, names)
            }

            // Pydantic AI OTel / Gemini: {parts: [{type: "tool_call", name: "..."}], role: "assistant"}
            if ('parts' in c && Array.isArray(c.parts)) {
                extractFromCalls(c.parts, names)
            }
        }
    }

    // If structured parsing found nothing, try Python repr fallback
    if (names.length === 0 && rawString && typeof rawString === 'string') {
        return extractFromPythonRepr(rawString)
    }

    return names
}
