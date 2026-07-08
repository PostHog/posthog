import { parseJSON } from '~/common/utils/json-parse'
import { PluginEvent } from '~/plugin-scaffold'

import { reassembleIndexedAttributes } from './traceloop'
import { OtelLibraryMiddleware } from './types'

// Arize OpenInference conventions (emitted by the OpenInference
// instrumentations for anthropic-sdk-go, openai-go, and the Python/JS
// ecosystem behind Phoenix/Arize). Messages arrive as indexed attributes
// (`llm.input_messages.0.message.role`), scalars as flat `llm.*` keys, and
// whole-payload fallbacks as `input.value` / `output.value`.

const SCALAR_MAP: [string, string][] = [
    ['llm.model_name', '$ai_model'],
    ['llm.provider', '$ai_provider'],
    ['llm.system', '$ai_provider'],
    ['llm.token_count.prompt', '$ai_input_tokens'],
    ['llm.token_count.completion', '$ai_output_tokens'],
    ['llm.token_count.prompt_details.cache_read', '$ai_cache_read_input_tokens'],
    ['llm.token_count.prompt_details.cache_write', '$ai_cache_creation_input_tokens'],
    ['llm.finish_reason', '$ai_stop_reason'],
    ['session.id', '$ai_session_id'],
]

const STRIP_KEYS = [
    'openinference.span.kind',
    'input.value',
    'input.mime_type',
    'output.value',
    'output.mime_type',
    'llm.token_count.total',
    'llm.invocation_parameters',
    'metadata',
]

const MESSAGE_FIELDS = ['message.role', 'message.content', 'message.tool_call_id', 'message.name']
const TOOL_CALL_GROUP = 'message.tool_calls'

function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// reassembleIndexedAttributes returns entries keyed by the raw dotted field
// names ("message.role", nested "tool_call.function.name"); flatten them into
// the plain message shape the trace view renders.
function toMessage(entry: Record<string, unknown>): Record<string, unknown> {
    const message: Record<string, unknown> = {}
    if (entry['message.role'] !== undefined) {
        message.role = entry['message.role']
    }
    if (entry['message.content'] !== undefined) {
        message.content = entry['message.content']
    }
    if (entry['message.tool_call_id'] !== undefined) {
        message.tool_call_id = entry['message.tool_call_id']
    }
    if (entry['message.name'] !== undefined) {
        message.name = entry['message.name']
    }
    if (Array.isArray(entry[TOOL_CALL_GROUP])) {
        const toolCalls = (entry[TOOL_CALL_GROUP] as unknown[]).filter(isObject).map((call) => ({
            id: call['tool_call.id'],
            type: 'function',
            function: {
                name: call['tool_call.function.name'],
                arguments: call['tool_call.function.arguments'],
            },
        }))
        if (toolCalls.length > 0) {
            message.tool_calls = toolCalls
        }
    }
    return message
}

function convertMessages(props: Record<string, unknown>, prefix: string, target: string): void {
    if (props[target] !== undefined) {
        return
    }
    const entries = reassembleIndexedAttributes(props, prefix, MESSAGE_FIELDS, [TOOL_CALL_GROUP])
    if (!entries) {
        return
    }
    const messages = entries.map(toMessage).filter((message) => Object.keys(message).length > 0)
    if (messages.length > 0) {
        props[target] = messages
    }
}

function convertTools(props: Record<string, unknown>): void {
    if (props['$ai_tools'] !== undefined) {
        return
    }
    const entries = reassembleIndexedAttributes(props, 'llm.tools.', ['tool.json_schema'], [])
    if (!entries) {
        return
    }
    const tools: unknown[] = []
    for (const entry of entries) {
        const schema = entry['tool.json_schema']
        if (typeof schema !== 'string') {
            continue
        }
        try {
            tools.push(parseJSON(schema))
        } catch {
            tools.push(schema)
        }
    }
    if (tools.length > 0) {
        props['$ai_tools'] = tools
    }
}

// `input.value` / `output.value` are whole-payload fallbacks (last user
// message text, concatenated response text) — only used when the indexed
// message attributes are absent, e.g. streaming spans that skip SSE parsing.
function convertValueFallbacks(props: Record<string, unknown>): void {
    if (props['$ai_input'] === undefined && typeof props['input.value'] === 'string') {
        props['$ai_input'] = [{ role: 'user', content: props['input.value'] }]
    }
    if (props['$ai_output_choices'] === undefined && typeof props['output.value'] === 'string') {
        props['$ai_output_choices'] = [{ role: 'assistant', content: props['output.value'] }]
    }
}

function convertInvocationParameters(props: Record<string, unknown>): void {
    const raw = props['llm.invocation_parameters']
    if (typeof raw !== 'string' || props['$ai_model_parameters'] !== undefined) {
        return
    }
    try {
        const parsed = parseJSON(raw)
        if (isObject(parsed)) {
            props['$ai_model_parameters'] = parsed
        }
    } catch {
        // Not JSON — drop it with the other stripped keys.
    }
}

function process(event: PluginEvent, next: () => void): void {
    if (!event.properties) {
        return next()
    }
    const props = event.properties

    next()

    for (const [otelKey, phKey] of SCALAR_MAP) {
        if (props[otelKey] !== undefined && props[phKey] === undefined) {
            props[phKey] = props[otelKey]
        }
        delete props[otelKey]
    }

    convertMessages(props, 'llm.input_messages.', '$ai_input')
    convertMessages(props, 'llm.output_messages.', '$ai_output_choices')
    convertTools(props)
    convertValueFallbacks(props)
    convertInvocationParameters(props)

    props['$ai_lib'] = 'opentelemetry/openinference'

    for (const key of STRIP_KEYS) {
        delete props[key]
    }
}

export const openinference: OtelLibraryMiddleware = {
    name: 'openinference',
    matches: (event) => event.properties?.['openinference.span.kind'] !== undefined,
    process,
}
