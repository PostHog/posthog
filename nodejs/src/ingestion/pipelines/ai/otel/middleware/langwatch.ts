import { parseJSON } from '~/common/utils/json-parse'
import { PluginEvent } from '~/plugin-scaffold'

import { OtelLibraryMiddleware } from './types'

const STRIP_KEYS = ['http.request.method', 'http.response.status_code', 'url.path', 'gen_ai.usage.total_tokens']

// Guard against pathological payloads, matching the ceiling used for
// older-spec `events` parsing in attribute-mapping.ts.
const MAX_VALUE_LENGTH = 500_000

// LangWatch wraps captured content as `{"type":"json"|"text","value":...}`.
function unwrapTypeWrapper(raw: unknown): unknown {
    if (typeof raw !== 'string' || raw.length > MAX_VALUE_LENGTH) {
        return undefined
    }
    let parsed: unknown
    try {
        parsed = parseJSON(raw)
    } catch {
        return undefined
    }
    if (typeof parsed !== 'object' || parsed === null || !('value' in parsed)) {
        return undefined
    }
    return (parsed as { value: unknown }).value
}

function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// openai-go marshals typed structs, so zero-value fields (`audio: {...}`,
// `refusal: ""`, `function_call: {...}`) come along for the ride. Keep only
// the fields the trace view renders, and only when they carry data.
function pickMessageFields(message: Record<string, unknown>): Record<string, unknown> {
    const picked: Record<string, unknown> = {}
    if (typeof message.role === 'string') {
        picked.role = message.role
    }
    if ('content' in message) {
        picked.content = message.content
    }
    if (Array.isArray(message.tool_calls) && message.tool_calls.length > 0) {
        picked.tool_calls = message.tool_calls
    }
    for (const key of ['tool_call_id', 'name', 'reasoning_content', 'refusal']) {
        const value = message[key]
        if (typeof value === 'string' && value.length > 0) {
            picked[key] = value
        }
    }
    return picked
}

function convertInput(props: Record<string, unknown>): void {
    const value = unwrapTypeWrapper(props['langwatch.input'])
    if (value === undefined || props['$ai_input'] !== undefined) {
        return
    }
    if (Array.isArray(value)) {
        // Chat Completions request messages — already in OpenAI shape.
        props['$ai_input'] = value
    } else if (typeof value === 'string') {
        // Responses API string input.
        props['$ai_input'] = [{ role: 'user', content: value }]
    }
}

// Chat Completions responses carry `choices[].message`; Responses API
// responses carry `output[]` items. Both flatten to plain messages, which is
// the shape the trace view renders directly.
function convertOutput(props: Record<string, unknown>): void {
    const value = unwrapTypeWrapper(props['langwatch.output'])
    if (value === undefined || props['$ai_output_choices'] !== undefined) {
        return
    }

    if (typeof value === 'string') {
        // Accumulated streaming text or Responses output_text.
        props['$ai_output_choices'] = [{ role: 'assistant', content: value }]
        return
    }
    if (!isObject(value)) {
        return
    }

    if (Array.isArray(value.choices)) {
        const messages = value.choices
            .filter(isObject)
            .map((choice) => (isObject(choice.message) ? pickMessageFields(choice.message) : {}))
        if (messages.length > 0) {
            props['$ai_output_choices'] = messages
        }
        if (props['$ai_stop_reason'] === undefined) {
            const first = value.choices.find(isObject)
            if (first && typeof first.finish_reason === 'string') {
                props['$ai_stop_reason'] = first.finish_reason
            }
        }
        return
    }

    if (Array.isArray(value.output)) {
        const messages: Record<string, unknown>[] = []
        for (const item of value.output.filter(isObject)) {
            if (item.type === 'message') {
                const content = Array.isArray(item.content)
                    ? item.content
                          .filter(isObject)
                          .map((part) => (typeof part.text === 'string' ? part.text : ''))
                          .filter((text) => text.length > 0)
                          .join('')
                    : item.content
                messages.push({ role: item.role ?? 'assistant', content })
            } else if (item.type === 'function_call') {
                messages.push({
                    role: 'assistant',
                    content: null,
                    tool_calls: [
                        {
                            id: item.call_id ?? item.id,
                            type: 'function',
                            function: { name: item.name, arguments: item.arguments },
                        },
                    ],
                })
            }
        }
        if (messages.length > 0) {
            props['$ai_output_choices'] = messages
        }
    }
}

// Responses API system prompt arrives as `langwatch.instructions` rather
// than a message; surface it the same way gen_ai.system_instructions is.
function convertInstructions(props: Record<string, unknown>): void {
    const instructions = props['langwatch.instructions']
    if (typeof instructions !== 'string' || instructions.length === 0) {
        return
    }
    const existing = props['$ai_input']
    if (Array.isArray(existing)) {
        const first: unknown = existing[0]
        if (!(isObject(first) && first.role === 'system')) {
            props['$ai_input'] = [{ role: 'system', content: instructions }, ...existing]
        }
    } else if (existing === undefined) {
        props['$ai_input'] = [{ role: 'system', content: instructions }]
    }
}

function process(event: PluginEvent, next: () => void): void {
    if (!event.properties) {
        return next()
    }
    const props = event.properties

    next()

    convertInput(props)
    convertOutput(props)
    convertInstructions(props)

    props['$ai_lib'] = 'opentelemetry/langwatch'

    for (const key of STRIP_KEYS) {
        delete props[key]
    }
    for (const key of Object.keys(props)) {
        if (key.startsWith('langwatch.')) {
            delete props[key]
        }
    }
}

export const langwatch: OtelLibraryMiddleware = {
    name: 'langwatch',
    matches: (event) => Object.keys(event.properties ?? {}).some((key) => key.startsWith('langwatch.')),
    process,
}
