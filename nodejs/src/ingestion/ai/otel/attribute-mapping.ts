import { PluginEvent } from '~/plugin-scaffold'

import { parseJSON } from '../../../utils/json-parse'

const ATTRIBUTE_MAP: Record<string, string> = {
    'gen_ai.input.messages': '$ai_input',
    'gen_ai.output.messages': '$ai_output_choices',
    'gen_ai.usage.input_tokens': '$ai_input_tokens',
    'gen_ai.usage.output_tokens': '$ai_output_tokens',
    'gen_ai.response.model': '$ai_model',
    'gen_ai.provider.name': '$ai_provider',
    'server.address': '$ai_base_url',
    'telemetry.sdk.name': '$ai_lib',
    'telemetry.sdk.version': '$ai_lib_version',
    $otel_span_name: '$ai_span_name',
}

const FALLBACK_ATTRIBUTE_MAP: Record<string, string> = {
    'gen_ai.system': '$ai_provider',
    'gen_ai.request.model': '$ai_model',
    'gen_ai.usage.prompt_tokens': '$ai_input_tokens',
    'gen_ai.usage.completion_tokens': '$ai_output_tokens',
}

const STRIP_ATTRIBUTES = new Set([
    'telemetry.sdk.language',
    'gen_ai.operation.name',
    'posthog.ai.debug',
    'user.id',
    'posthog.distinct_id',
    'llm.request.type',
])

const JSON_PARSE_PROPERTIES = new Set(['$ai_input', '$ai_output_choices'])

// Older OTel GenAI spec emits messages as span events rather than
// `gen_ai.input.messages` / `gen_ai.output.messages` attributes. Logfire
// serializes those span events into a single `events` span attribute.
const OLDER_SPEC_INPUT_EVENT_NAMES: Record<string, string> = {
    'gen_ai.system.message': 'system',
    'gen_ai.user.message': 'user',
    'gen_ai.assistant.message': 'assistant',
    'gen_ai.tool.message': 'tool',
}
const OLDER_SPEC_CHOICE_EVENT_NAME = 'gen_ai.choice'

const REQUEST_TYPE_TO_EVENT: Record<string, string> = {
    chat: '$ai_generation',
    completion: '$ai_generation',
    embedding: '$ai_embedding',
    embeddings: '$ai_embedding',
}

function reclassifyByRequestType(event: PluginEvent): void {
    if (event.event !== '$ai_span') {
        return
    }
    const requestType = event.properties!['llm.request.type']
    if (typeof requestType === 'string' && requestType in REQUEST_TYPE_TO_EVENT) {
        event.event = REQUEST_TYPE_TO_EVENT[requestType]
    }
}

export function mapOtelAttributes(event: PluginEvent): void {
    if (!event.properties) {
        return
    }

    reclassifyByRequestType(event)

    for (const [otelKey, phKey] of Object.entries(ATTRIBUTE_MAP)) {
        if (event.properties[otelKey] !== undefined) {
            let value = event.properties[otelKey]
            if (JSON_PARSE_PROPERTIES.has(phKey) && typeof value === 'string') {
                try {
                    value = parseJSON(value)
                } catch {
                    // Keep original string value if parsing fails
                }
            }
            event.properties[phKey] = value
            delete event.properties[otelKey]
        }
    }

    for (const [otelKey, phKey] of Object.entries(FALLBACK_ATTRIBUTE_MAP)) {
        if (event.properties[otelKey] !== undefined && event.properties[phKey] === undefined) {
            event.properties[phKey] = event.properties[otelKey]
        }
        delete event.properties[otelKey]
    }

    convertOlderSpecEvents(event)

    computeLatency(event)
    promoteRootSpanToTrace(event)

    for (const key of STRIP_ATTRIBUTES) {
        delete event.properties[key]
    }
}

function computeLatency(event: PluginEvent): void {
    const props = event.properties!
    const startStr = props['$otel_start_time_unix_nano']
    const endStr = props['$otel_end_time_unix_nano']

    if (typeof startStr === 'string' && typeof endStr === 'string') {
        try {
            const start = BigInt(startStr)
            const end = BigInt(endStr)
            if (end > start) {
                props['$ai_latency'] = Number(end - start) / 1_000_000_000
            }
        } catch {
            // Ignore malformed nanosecond timestamps
        }
    }

    delete props['$otel_start_time_unix_nano']
    delete props['$otel_end_time_unix_nano']
}

function promoteRootSpanToTrace(event: PluginEvent): void {
    if (event.event === '$ai_span' && !event.properties!['$ai_parent_id']) {
        event.event = '$ai_trace'
    }
}

function parseOlderSpecEventsAttribute(raw: unknown): Record<string, unknown>[] | undefined {
    let value: unknown = raw
    if (typeof value === 'string') {
        try {
            value = parseJSON(value)
        } catch {
            return undefined
        }
    }
    if (!Array.isArray(value)) {
        return undefined
    }
    return value.filter(
        (item): item is Record<string, unknown> => typeof item === 'object' && item !== null && !Array.isArray(item)
    )
}

function reconstructInputMessage(entry: Record<string, unknown>, eventName: string): Record<string, unknown> | null {
    const role = typeof entry.role === 'string' ? entry.role : OLDER_SPEC_INPUT_EVENT_NAMES[eventName]
    if (!role) {
        return null
    }
    const message: Record<string, unknown> = { role }
    if ('content' in entry) {
        message.content = entry.content
    }
    if ('tool_calls' in entry) {
        message.tool_calls = entry.tool_calls
    }
    if ('tool_call_id' in entry) {
        message.tool_call_id = entry.tool_call_id
    }
    return message
}

function reconstructOutputChoice(entry: Record<string, unknown>): Record<string, unknown> | null {
    // Emit flat messages (matching newer-spec `gen_ai.output.messages`) so the
    // frontend renderer picks them up directly. A `{ index, message }` wrapper
    // would only be unwrapped by `isLiteLLMChoice`, which requires a
    // `finish_reason` field we don't have.
    if (typeof entry.message === 'object' && entry.message !== null && !Array.isArray(entry.message)) {
        return entry.message as Record<string, unknown>
    }
    if ('role' in entry || 'content' in entry || 'tool_calls' in entry) {
        const message: Record<string, unknown> = {}
        if ('role' in entry) {
            message.role = entry.role
        }
        if ('content' in entry) {
            message.content = entry.content
        }
        if ('tool_calls' in entry) {
            message.tool_calls = entry.tool_calls
        }
        return message
    }
    return null
}

function convertOlderSpecEvents(event: PluginEvent): void {
    const props = event.properties!
    if (!('events' in props)) {
        return
    }

    try {
        const entries = parseOlderSpecEventsAttribute(props.events)
        if (!entries) {
            return
        }

        const inputs: { message: Record<string, unknown>; index: number; order: number }[] = []
        const choices: Record<string, unknown>[] = []

        for (let order = 0; order < entries.length; order++) {
            const entry = entries[order]
            const eventName = typeof entry['event.name'] === 'string' ? (entry['event.name'] as string) : undefined
            if (!eventName) {
                continue
            }

            if (eventName in OLDER_SPEC_INPUT_EVENT_NAMES) {
                const message = reconstructInputMessage(entry, eventName)
                if (message) {
                    const index =
                        typeof entry['gen_ai.message.index'] === 'number'
                            ? (entry['gen_ai.message.index'] as number)
                            : Number.NaN
                    inputs.push({ message, index, order })
                }
            } else if (eventName === OLDER_SPEC_CHOICE_EVENT_NAME) {
                const choice = reconstructOutputChoice(entry)
                if (choice) {
                    choices.push(choice)
                }
            }
        }

        if (inputs.length > 0 && props['$ai_input'] === undefined) {
            const allIndexed = inputs.every((i) => Number.isFinite(i.index))
            const sorted = allIndexed ? [...inputs].sort((a, b) => a.index - b.index || a.order - b.order) : inputs
            props['$ai_input'] = sorted.map((i) => i.message)
        }

        if (choices.length > 0 && props['$ai_output_choices'] === undefined) {
            props['$ai_output_choices'] = choices
        }
    } catch {
        // Never let malformed data break the rest of the mapping pipeline.
    } finally {
        delete props.events
    }
}
