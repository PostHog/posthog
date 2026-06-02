import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { CompatMessage } from './types'
import { extractTextContent, hasStringContentField, normalizeMessages, readAiInput } from './utils'

const GENERIC_TRACE_NAMES = new Set(['langgraph', 'runnablesequence', 'chatprompttemplate'])

const DEFAULT_MAX_LENGTH = 120
const WORD_BOUNDARY_LOOKBACK = 20

/**
 * Resolve a human-readable title for a session, given its first trace.
 *
 * Priority:
 * 1. First user-role message in `trace.inputState.messages`.
 * 2. First user-role message in the first event's `$ai_input_state.messages`.
 * 3. First user-role message in the first generation's `$ai_input`.
 * 4. `$mcp_intent` from the first event's properties.
 * 5. `trace.traceName` when it's not a generic framework root span name.
 *
 * Returns `null` if no signal is available, so that caller decides on fallback
 */
export function resolveSessionTitle(trace: LLMTrace | undefined, maxLength = DEFAULT_MAX_LENGTH): string | null {
    if (!trace) {
        return null
    }

    const sortedEvents = sortByCreatedAt(trace.events)
    const firstEvent = sortedEvents[0]

    const fromInputState = firstUserText(trace.inputState)
    if (fromInputState) {
        return truncate(fromInputState, maxLength)
    }

    if (firstEvent) {
        const fromSpanInputState = firstUserText(firstEvent.properties.$ai_input_state)
        if (fromSpanInputState) {
            return truncate(fromSpanInputState, maxLength)
        }
    }

    const firstGeneration = sortedEvents.find((e) => e.event === '$ai_generation')
    if (firstGeneration) {
        const fromGenInput = firstUserText(readAiInput(firstGeneration.properties))
        if (fromGenInput) {
            return truncate(fromGenInput, maxLength)
        }
    }

    if (firstEvent) {
        const mcpIntent = firstEvent.properties.$mcp_intent
        if (typeof mcpIntent === 'string' && mcpIntent.trim().length > 0) {
            return truncate(mcpIntent, maxLength)
        }
    }

    if (typeof trace.traceName === 'string' && trace.traceName.length > 0) {
        if (!GENERIC_TRACE_NAMES.has(trace.traceName.toLowerCase())) {
            return truncate(trace.traceName, maxLength)
        }
    }

    return null
}

function sortByCreatedAt(events: LLMTraceEvent[] | undefined): LLMTraceEvent[] {
    if (!events?.length) {
        return []
    }
    return [...events].sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime())
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
    const normalized = normalizeMessages(messages, 'user')
    for (const message of normalized) {
        if (message.role !== 'user') {
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
