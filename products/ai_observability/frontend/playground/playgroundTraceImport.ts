import { isObject } from 'lib/utils/guards'

import { normalizeRole, safeStringify } from '../utils'
import type { Message, MessageToolCall } from './llmPlaygroundPromptsLogic'

export interface RawMessage {
    role: string
    content: unknown
    tool_calls?: unknown
    tool_call_id?: unknown
    type?: string
    name?: unknown
    call_id?: unknown
    arguments?: unknown
    output?: unknown
}

enum InputMessageRole {
    User = 'user',
    Assistant = 'assistant',
}

// Formats a typed content block (one with a `type` field) into readable text.
// Returns null for unrecognized types so callers can fall through.
function formatContentBlock(part: Record<string, unknown>): string | null {
    const type = part.type

    if (type === 'text' || type === 'output_text' || type === 'input_text') {
        const text = part.text
        return typeof text === 'string' && text.trim().length > 0 ? text : null
    }

    return null
}

function extractTextFromMessagePart(part: unknown): string | null {
    if (!isObject(part)) {
        return null
    }

    // Typed content blocks are handled by formatContentBlock, which checks
    // `type` before any generic field extraction — preventing e.g. a
    // tool_result's `.content` from being misidentified as plain text.
    if (typeof part.type === 'string') {
        return formatContentBlock(part)
    }

    // Untyped objects: try common text field names
    if (typeof part.text === 'string' && part.text.trim().length > 0) {
        return part.text
    }

    if (typeof part.content === 'string' && part.content.trim().length > 0) {
        return part.content
    }

    if (typeof part.output_text === 'string' && part.output_text.trim().length > 0) {
        return part.output_text
    }

    if (typeof part.value === 'string' && part.value.trim().length > 0) {
        return part.value
    }

    return null
}

function normalizeMessageContent(content: unknown): string {
    if (content === null || content === undefined) {
        return ''
    }

    if (typeof content === 'string') {
        return content
    }

    if (Array.isArray(content)) {
        const extractedTextParts = content
            .map(extractTextFromMessagePart)
            .filter((part): part is string => part !== null)

        if (extractedTextParts.length > 0) {
            return extractedTextParts.join('\n\n')
        }
    }

    return safeStringify(content)
}

function toolCallArgumentsString(value: unknown): string {
    if (typeof value === 'string') {
        return value
    }
    return value === undefined || value === null ? '{}' : safeStringify(value)
}

// Anthropic `tool_use` and OpenAI Responses API `function_call` blocks
function toolCallFromBlock(block: Record<string, unknown>): MessageToolCall {
    const id = block.type === 'function_call' ? block.call_id : block.id
    return {
        id: typeof id === 'string' ? id : '',
        name: typeof block.name === 'string' ? block.name : 'unknown',
        arguments: toolCallArgumentsString(block.type === 'function_call' ? block.arguments : block.input),
    }
}

// OpenAI chat `tool_calls` arrays on assistant messages
function toolCallsFromOpenAI(toolCalls: unknown): MessageToolCall[] {
    if (!Array.isArray(toolCalls)) {
        return []
    }
    return toolCalls.filter(isObject).map((tc) => {
        const fn = isObject(tc.function) ? tc.function : tc
        return {
            id: typeof tc.id === 'string' ? tc.id : '',
            name: typeof fn.name === 'string' ? fn.name : 'unknown',
            arguments: toolCallArgumentsString(fn.arguments),
        }
    })
}

function findToolName(conversation: Message[], callId: string | undefined): string | undefined {
    if (!callId) {
        return undefined
    }
    for (let i = conversation.length - 1; i >= 0; i--) {
        const match = conversation[i].toolCalls?.find((toolCall) => toolCall.id === callId)
        if (match?.name) {
            return match.name
        }
    }
    return undefined
}

function toolResultMessage(conversation: Message[], callId: unknown, content: unknown): Message {
    const id = typeof callId === 'string' && callId ? callId : undefined
    const name = findToolName(conversation, id)
    return {
        role: 'tool',
        content: normalizeMessageContent(content),
        ...(id ? { toolCallId: id } : {}),
        ...(name ? { toolName: name } : {}),
    }
}

function isToolCallBlock(part: unknown): part is Record<string, unknown> {
    return isObject(part) && (part.type === 'tool_use' || part.type === 'function_call')
}

function isToolResultBlock(part: unknown): part is Record<string, unknown> {
    return isObject(part) && (part.type === 'tool_result' || part.type === 'function_call_output')
}

function appendBlocks(
    conversation: Message[],
    role: 'user' | 'assistant',
    blocks: unknown[],
    extraToolCalls: MessageToolCall[] = []
): void {
    const textParts: string[] = []
    const toolCalls: MessageToolCall[] = [...extraToolCalls]
    const toolResults: { callId: unknown; content: unknown }[] = []

    for (const part of blocks) {
        if (isToolCallBlock(part)) {
            toolCalls.push(toolCallFromBlock(part))
        } else if (isToolResultBlock(part)) {
            toolResults.push({
                callId: part.type === 'tool_result' ? part.tool_use_id : part.call_id,
                content: part.type === 'tool_result' ? part.content : part.output,
            })
        } else {
            const text = extractTextFromMessagePart(part)
            if (text !== null) {
                textParts.push(text)
            }
        }
    }

    if (textParts.length === 0 && toolCalls.length === 0 && toolResults.length === 0) {
        // Nothing recognizable: keep the raw payload visible rather than dropping the turn.
        conversation.push({ role, content: blocks.length > 0 ? safeStringify(blocks) : '' })
        return
    }

    const content = textParts.join('\n\n')
    const pushTextAndCalls = (): void => {
        if (toolCalls.length > 0) {
            conversation.push({ role: 'assistant', content, toolCalls })
        } else if (role === 'assistant') {
            if (content || toolResults.length === 0) {
                conversation.push({ role: 'assistant', content })
            }
        } else if (content) {
            conversation.push({ role: 'user', content })
        }
    }
    const pushResults = (): void => {
        for (const result of toolResults) {
            conversation.push(toolResultMessage(conversation, result.callId, result.content))
        }
    }

    // Tool results become their own turns. In a user message they answer the preceding
    // assistant call, so they go before the user's text; in an assistant message they follow it.
    if (role === 'user') {
        pushResults()
        pushTextAndCalls()
    } else {
        pushTextAndCalls()
        pushResults()
    }
}

/**
 * Appends a raw trace message to a running conversation as structured playground messages:
 * assistant tool calls become `toolCalls` data, tool results become tool-role messages, and
 * anything unrecognizable keeps its text form. One raw message can produce several playground
 * messages (e.g. an Anthropic user message holding two tool_result blocks).
 */
export function appendRawMessage(conversation: Message[], raw: RawMessage): void {
    // OpenAI Responses API sends function_call / function_call_output items at the top level
    // of the conversation array with no `role`.
    if (typeof raw.role !== 'string' && (raw.type === 'function_call' || raw.type === 'function_call_output')) {
        if (raw.type === 'function_call') {
            const toolCall = toolCallFromBlock(raw as unknown as Record<string, unknown>)
            const previous = conversation[conversation.length - 1]
            // Parallel calls arrive as consecutive items but belong to one model turn.
            if (previous?.role === 'assistant') {
                previous.toolCalls = [...(previous.toolCalls ?? []), toolCall]
            } else {
                conversation.push({ role: 'assistant', content: '', toolCalls: [toolCall] })
            }
        } else {
            conversation.push(toolResultMessage(conversation, raw.call_id, raw.output))
        }
        return
    }

    const normalizedRole = normalizeRole(raw.role, InputMessageRole.User)

    if (normalizedRole === 'tool') {
        conversation.push(toolResultMessage(conversation, raw.tool_call_id, raw.content))
        return
    }

    const role: 'user' | 'assistant' =
        normalizedRole === InputMessageRole.Assistant ? InputMessageRole.Assistant : InputMessageRole.User
    const topLevelToolCalls = toolCallsFromOpenAI(raw.tool_calls)

    if (Array.isArray(raw.content)) {
        appendBlocks(conversation, role, raw.content, topLevelToolCalls)
        return
    }

    conversation.push({
        role,
        content: normalizeMessageContent(raw.content),
        ...(topLevelToolCalls.length > 0 ? { toolCalls: topLevelToolCalls } : {}),
    })
}

// Safety cap on recursion depth in flattenOutputMessages. Trace payloads can't have true cycles
// (they come from `JSON.parse`), but deeply nested `{ message: { message: … } }` chains or arrays
// of arrays could run the stack down — bail early and hand back an empty list instead.
const MAX_OUTPUT_FLATTEN_DEPTH = 100

// Flattens a raw generation output (string, single message, message array, or an
// OpenAI/LiteLLM-style { choices: [...] } wrapper) into a list of RawMessage entries
// without splitting structured content blocks — unlike `normalizeMessages` from utils,
// which fans out tool_use/tool_result blocks into separate display bubbles.
export function flattenOutputMessages(output: unknown, depth: number = 0): RawMessage[] {
    if (output == null || depth > MAX_OUTPUT_FLATTEN_DEPTH) {
        return []
    }

    if (typeof output === 'string') {
        return [{ role: InputMessageRole.Assistant, content: output }]
    }

    if (Array.isArray(output)) {
        return output.flatMap((item) => flattenOutputMessages(item, depth + 1))
    }

    if (isObject(output)) {
        if (Array.isArray(output.choices)) {
            return output.choices.flatMap((item) => flattenOutputMessages(item, depth + 1))
        }
        if (isObject(output.message)) {
            return flattenOutputMessages(output.message, depth + 1)
        }
        // OpenAI Responses API top-level function_call / function_call_output items have no role.
        // Pass them through untouched so appendRawMessage can turn them into structured turns.
        if (output.type === 'function_call' || output.type === 'function_call_output') {
            return [output as unknown as RawMessage]
        }
        return [
            {
                role: typeof output.role === 'string' ? output.role : InputMessageRole.Assistant,
                content: output.content,
                tool_calls: output.tool_calls,
                tool_call_id: output.tool_call_id,
            },
        ]
    }

    return []
}
