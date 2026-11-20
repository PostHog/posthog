// Agents send tool results back to the model in the next request, so a generation's results are
// the trailing run of tool-result items in $ai_input. Earlier results were already counted by the
// generation that received them.
import { MAX_TOOLS_PER_EVENT, sanitizeToolName } from './extract-tool-calls'

export const MAX_TOOL_INTENT_LENGTH = 500

export interface ToolResult {
    name: string | null
    isError: boolean
}

type Item = Record<string, unknown>

const isObject = (value: unknown): value is Item => typeof value === 'object' && value !== null && !Array.isArray(value)

const asString = (value: unknown): string | undefined =>
    typeof value === 'string' && value.length > 0 ? value : undefined

const RESULT_PART_TYPES = new Set(['tool_result', 'tool-result', 'tool_call_response', 'function_response'])
const FLAT_RESULT_TYPES = new Set([
    'function_call_output',
    'custom_tool_call_output',
    'function_call_result',
    'computer_call_output',
])
const CALL_PART_TYPES = new Set(['tool_use', 'tool-call', 'tool_call', 'function', 'functionCall'])
const FLAT_CALL_TYPES = new Set(['function_call', 'custom_tool_call', 'computer_call'])

// Vercel AI SDK v5 tool-result output types that mean the tool failed.
const ERROR_OUTPUT_TYPES = new Set(['error-text', 'error-json'])

// A tool that failed without an explicit error flag usually says so first thing.
const ERROR_TEXT_PATTERN = /^\s*(error|exception|traceback)\b/i

function unwrapMessages(value: unknown): unknown[] | null {
    if (Array.isArray(value)) {
        return value
    }
    if (isObject(value)) {
        for (const key of ['messages', 'input', 'choices']) {
            if (Array.isArray(value[key])) {
                return value[key] as unknown[]
            }
        }
    }
    return null
}

function partsOf(item: Item): unknown[] | null {
    if (Array.isArray(item.content)) {
        return item.content
    }
    if (Array.isArray(item.parts)) {
        return item.parts
    }
    return null
}

function textOf(value: unknown): string | undefined {
    if (typeof value === 'string') {
        return value
    }
    if (Array.isArray(value)) {
        for (const part of value) {
            if (isObject(part) && typeof part.text === 'string') {
                return part.text
            }
        }
        return undefined
    }
    if (isObject(value)) {
        if (typeof value.value === 'string') {
            return value.value
        }
        if (typeof value.text === 'string') {
            return value.text
        }
    }
    return undefined
}

function explicitError(result: Item): boolean | undefined {
    if (typeof result.is_error === 'boolean') {
        return result.is_error
    }
    if (typeof result.isError === 'boolean') {
        return result.isError
    }
    if (result.status === 'error') {
        return true
    }
    for (const key of ['output', 'content', 'response', 'result']) {
        const nested = result[key]
        if (isObject(nested)) {
            if (typeof nested.type === 'string' && ERROR_OUTPUT_TYPES.has(nested.type)) {
                return true
            }
            // MCP CallToolResult
            if (typeof nested.isError === 'boolean') {
                return nested.isError
            }
        }
    }
    return undefined
}

function resultIsError(result: Item): boolean {
    const explicit = explicitError(result)
    if (explicit !== undefined) {
        return explicit
    }
    for (const key of ['output', 'content', 'response', 'result']) {
        const text = textOf(result[key])
        if (text !== undefined) {
            return ERROR_TEXT_PATTERN.test(text)
        }
    }
    return false
}

interface RawResult {
    id: string | undefined
    name: string | undefined
    isError: boolean
}

function rawResult(result: Item, id: unknown, name: unknown): RawResult {
    return { id: asString(id), name: asString(name), isError: resultIsError(result) }
}

function resultsOf(item: unknown): RawResult[] | null {
    if (!isObject(item)) {
        return null
    }

    if (typeof item.type === 'string' && FLAT_RESULT_TYPES.has(item.type)) {
        return [rawResult(item, item.call_id ?? item.callId ?? item.id, item.name)]
    }

    const parts = partsOf(item)
    if (parts) {
        const results: RawResult[] = []
        for (const part of parts) {
            if (!isObject(part)) {
                continue
            }
            if (typeof part.type === 'string' && RESULT_PART_TYPES.has(part.type)) {
                results.push(
                    rawResult(
                        part,
                        part.tool_use_id ?? part.toolCallId ?? part.tool_call_id ?? part.id,
                        part.toolName ?? part.name
                    )
                )
            } else if (isObject(part.functionResponse)) {
                const response = part.functionResponse
                results.push(rawResult(response, response.id, response.name))
            }
        }
        if (results.length > 0) {
            return results
        }
    }

    if (item.role === 'tool' || item.role === 'function') {
        return [rawResult(item, item.tool_call_id ?? item.toolCallId, item.name)]
    }

    return null
}

function collectCallNames(item: unknown, names: Map<string, string>): void {
    if (!isObject(item)) {
        return
    }
    const add = (id: unknown, name: unknown): void => {
        const callId = asString(id)
        const toolName = asString(name)
        if (callId && toolName) {
            names.set(callId, toolName)
        }
    }

    if (typeof item.type === 'string' && FLAT_CALL_TYPES.has(item.type)) {
        add(item.call_id ?? item.callId ?? item.id, item.name)
    }

    const toolCalls = Array.isArray(item.tool_calls) ? item.tool_calls : []
    for (const call of toolCalls) {
        if (isObject(call)) {
            add(call.id, isObject(call.function) ? call.function.name : call.name)
        }
    }

    for (const part of partsOf(item) ?? []) {
        if (!isObject(part) || typeof part.type !== 'string' || !CALL_PART_TYPES.has(part.type)) {
            continue
        }
        if (isObject(part.toolInvoke)) {
            add(part.toolInvoke.id, part.toolInvoke.name)
            continue
        }
        add(
            part.id ?? part.toolCallId ?? part.tool_call_id,
            part.name ?? part.toolName ?? (isObject(part.function) ? part.function.name : undefined)
        )
    }
}

export function extractToolResults(input: unknown): ToolResult[] {
    const items = unwrapMessages(input)
    if (!items || items.length === 0) {
        return []
    }

    const trailing: RawResult[] = []
    for (let i = items.length - 1; i >= 0; i--) {
        const results = resultsOf(items[i])
        if (results === null) {
            break
        }
        trailing.unshift(...results)
        if (trailing.length >= MAX_TOOLS_PER_EVENT) {
            break
        }
    }
    if (trailing.length === 0) {
        return []
    }

    const callNames = new Map<string, string>()
    for (const item of items) {
        collectCallNames(item, callNames)
    }

    return trailing.slice(-MAX_TOOLS_PER_EVENT).map((result) => {
        const rawName = result.name ?? (result.id ? callNames.get(result.id) : undefined)
        return { name: rawName ? sanitizeToolName(rawName) : null, isError: result.isError }
    })
}

// Null unless every tool is named: a partial list, e.g. with a provider built-in tool such as
// {type: "web_search_preview"}, would flag the unnamed tools as unknown.
export function extractDefinedToolNames(tools: unknown): Set<string> | null {
    const names = new Set<string>()
    const add = (raw: unknown): boolean => {
        const name = typeof raw === 'string' ? sanitizeToolName(raw) : null
        if (name === null) {
            return false
        }
        names.add(name)
        return true
    }

    if (isObject(tools) && !('name' in tools) && !('function' in tools) && !('functionDeclarations' in tools)) {
        // Vercel AI SDK passes tools as a {name: definition} record.
        for (const key of Object.keys(tools)) {
            add(key)
        }
        return names.size > 0 ? names : null
    }

    const list = Array.isArray(tools) ? tools : isObject(tools) ? [tools] : null
    if (!list || list.length === 0) {
        return null
    }

    for (const tool of list) {
        if (typeof tool === 'string') {
            if (!add(tool)) {
                return null
            }
            continue
        }
        if (!isObject(tool)) {
            return null
        }
        if (Array.isArray(tool.functionDeclarations)) {
            for (const declaration of tool.functionDeclarations) {
                if (!isObject(declaration) || !add(declaration.name)) {
                    return null
                }
            }
            continue
        }
        const name = isObject(tool.function) ? tool.function.name : (tool.name ?? tool.toolName)
        if (!add(name)) {
            return null
        }
    }
    return names.size > 0 ? names : null
}

export function findUnknownTools(called: string[], defined: Set<string>): string[] {
    const unknown: string[] = []
    for (const name of called) {
        if (!defined.has(name) && !unknown.includes(name)) {
            unknown.push(name)
        }
    }
    return unknown
}

const TEXT_PART_TYPES = new Set(['text', 'output_text'])

// Structured output (JSON mode) is data for the caller, not a statement of intent.
const looksLikeJson = (text: string): boolean => /^\s*[[{]/.test(text)

function collectText(value: unknown, texts: string[]): void {
    if (typeof value === 'string') {
        if (!looksLikeJson(value)) {
            texts.push(value)
        }
        return
    }
    if (!Array.isArray(value)) {
        return
    }
    for (const part of value) {
        if (!isObject(part) || typeof part.type !== 'string' || !TEXT_PART_TYPES.has(part.type)) {
            continue
        }
        const text = part.text ?? part.content
        if (typeof text === 'string' && !looksLikeJson(text)) {
            texts.push(text)
        }
    }
}

export function extractToolCallIntent(outputChoices: unknown): string | null {
    const choices = unwrapMessages(outputChoices)
    if (!choices) {
        return null
    }

    const texts: string[] = []
    for (const choice of choices) {
        if (!isObject(choice)) {
            continue
        }
        const message = isObject(choice.message) ? choice.message : choice
        if (message.role !== undefined && message.role !== 'assistant' && message.role !== 'model') {
            continue
        }
        collectText(message.content, texts)
        collectText(message.parts, texts)
    }

    const intent = texts.join(' ').replace(/\s+/g, ' ').trim()
    if (intent.length === 0) {
        return null
    }
    return intent.length > MAX_TOOL_INTENT_LENGTH ? `${intent.slice(0, MAX_TOOL_INTENT_LENGTH - 1)}…` : intent
}
