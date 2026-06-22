import { normalizeMessages } from './messageNormalization'
import { CompatMessage } from './types'
import {
    extractTextContent,
    hasStringContentField,
    isInternalTagMessage,
    isInternalToolResultUserMessage,
} from './utils'

// Framework root-span names that carry no meaning as a title, so we ignore them.
const GENERIC_TRACE_NAMES = new Set(['langgraph', 'runnablesequence', 'chatprompttemplate'])

const DEFAULT_MAX_LENGTH = 120
const WORD_BOUNDARY_LOOKBACK = 20

/**
 * Resolve a session title from its opening payloads, in priority order:
 * 1. first real user message in the trace `input_state`,
 * 2. first real user message in the earliest generation `input`,
 * 3. the trace name, unless it's a generic framework root-span name.
 *
 * Returns `null` when none yield a usable title, so that caller decides on fallback
 */
export function resolveTitleFromInputs(
    inputState: unknown,
    generationInput: unknown,
    traceName?: unknown,
    maxLength = DEFAULT_MAX_LENGTH
): string | null {
    const fromInputState = firstUserText(inputState)
    if (fromInputState) {
        return truncate(fromInputState, maxLength)
    }

    const fromGenInput = firstUserText(generationInput)
    if (fromGenInput) {
        return truncate(fromGenInput, maxLength)
    }

    if (typeof traceName === 'string') {
        const trimmed = traceName.trim()
        if (trimmed.length > 0 && !GENERIC_TRACE_NAMES.has(trimmed.toLowerCase())) {
            return truncate(trimmed, maxLength)
        }
    }

    return null
}

/**
 * Extract the first user-role message's text from any payload shape
 * `normalizeMessages` understands — including `{messages: [...]}` wrappers used
 * by LangGraph/Claude Agent SDK input_state. Role mapping (`human` → `user`,
 * `type` → `role`, etc.) is delegated entirely to `normalizeMessages`.
 *
 * We default to role `user` following the convention in the codebase
 * (e.g. pickFirstInputMessage and sentiment/extraction.py)
 */
function firstUserText(inputPayload: unknown): string | null {
    const messages = Array.isArray(inputPayload)
        ? inputPayload
        : inputPayload &&
            typeof inputPayload === 'object' &&
            Array.isArray((inputPayload as { messages?: unknown }).messages)
          ? (inputPayload as { messages: unknown[] }).messages
          : inputPayload
    const normalized = normalizeMessages(messages, 'user').messages
    for (const message of normalized) {
        if (message.role !== 'user') {
            continue
        }
        if (isInternalTagMessage(message) || isInternalToolResultUserMessage(message)) {
            continue
        }
        const text = messageContentToText(message.content)
        if (text) {
            return text
        }
    }
    return null
}

function messageContentToText(content: CompatMessage['content']): string | null {
    let raw: string | undefined
    if (typeof content === 'string') {
        raw = content
    } else if (Array.isArray(content)) {
        raw = content.map(extractTextContent).filter(Boolean).join(' ')
    } else if (hasStringContentField(content)) {
        raw = content.content
    }
    const collapsed = raw?.replace(/\s+/g, ' ').trim()
    return collapsed ? collapsed : null
}

function truncate(value: string, maxLength: number): string {
    if (value.length <= maxLength) {
        return value
    }
    // Back off to the previous space within the last WORD_BOUNDARY_LOOKBACK chars
    // so we don't cut mid-word; if no space is found, hard-cut.
    const hardCut = value.slice(0, maxLength)
    const lastSpace = hardCut.lastIndexOf(' ')
    const cutAt = lastSpace > maxLength - WORD_BOUNDARY_LOOKBACK ? lastSpace : maxLength
    return `${value.slice(0, cutAt).trimEnd()}…`
}
