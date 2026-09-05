import { parseJSON } from '~/common/utils/json-parse'
import { PluginEvent } from '~/plugin-scaffold'

import { reassembleIndexedAttributes } from './traceloop'
import { OtelLibraryMiddleware } from './types'

// Classification-only and plumbing keys. `openinference.span.kind` already
// drove event classification in capture (rust/capture/src/otel/providers.rs);
// `llm.token_count.total` is derivable from the prompt/completion counts the
// fallback map keeps.
const STRIP_KEYS = [
    'openinference.span.kind',
    'llm.invocation_parameters',
    'llm.token_count.total',
    'input.mime_type',
    'output.mime_type',
    'embedding.invocation_parameters',
]

// Flattened key families consumed (or deliberately dropped) by this
// middleware. Whatever reassembly did not pick up — e.g. multimodal
// `message.contents.*` parts, or `embedding.embeddings.*` vectors, which are
// far too large to ride along as event properties — must not leak into the
// final event.
const STRIP_PREFIXES = [
    'llm.input_messages.',
    'llm.output_messages.',
    'llm.tools.',
    'embedding.embeddings.',
    'openinference.',
]

// OpenInference flattens each message into indexed keys under a `message.`
// namespace: `llm.input_messages.0.message.role`, `...0.message.content`,
// `...0.message.tool_calls.0.tool_call.function.name`, and so on
// (spec/tool_calling.md in Arize-ai/openinference).
const MESSAGE_FIELDS = ['message.role', 'message.content', 'message.tool_call_id', 'message.name']
const MESSAGE_NESTED_GROUPS = ['message.tool_calls']

// Rebuild the gen_ai-shaped message every other producer emits, converting
// `tool_call.*` sub-keys into the OpenAI-style `tool_calls` entries the trace
// view and the judge input flattener both render.
function toStandardMessage(entry: Record<string, unknown>): Record<string, unknown> {
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
    const toolCalls = entry['message.tool_calls']
    if (Array.isArray(toolCalls)) {
        message.tool_calls = toolCalls
            .filter((tc): tc is Record<string, unknown> => typeof tc === 'object' && tc !== null)
            .map((tc) => {
                const call: Record<string, unknown> = { type: 'function' }
                if (tc['tool_call.id'] !== undefined) {
                    call.id = tc['tool_call.id']
                }
                const fn: Record<string, unknown> = {}
                if (tc['tool_call.function.name'] !== undefined) {
                    fn.name = tc['tool_call.function.name']
                }
                if (tc['tool_call.function.arguments'] !== undefined) {
                    fn.arguments = tc['tool_call.function.arguments']
                }
                call.function = fn
                return call
            })
    }
    return message
}

function reassembleMessages(props: Record<string, unknown>, prefix: string): Record<string, unknown>[] | undefined {
    const entries = reassembleIndexedAttributes(props, prefix, MESSAGE_FIELDS, MESSAGE_NESTED_GROUPS)
    return entries?.map(toStandardMessage)
}

// `input.value` / `output.value` are strings; the companion mime_type says
// whether they hold JSON.
function parseValueAttribute(value: unknown, mimeType: unknown): unknown {
    if (typeof value === 'string' && mimeType === 'application/json') {
        try {
            return parseJSON(value)
        } catch {
            return value
        }
    }
    return value
}

function process(event: PluginEvent, next: () => void): void {
    if (!event.properties) {
        return next()
    }
    const props = event.properties

    next()

    if (props['$ai_input'] === undefined) {
        const messages = reassembleMessages(props, 'llm.input_messages.')
        if (messages) {
            props['$ai_input'] = messages
        }
    }

    if (props['$ai_output_choices'] === undefined) {
        const messages = reassembleMessages(props, 'llm.output_messages.')
        if (messages) {
            props['$ai_output_choices'] = messages
        }
    }

    if (props['$ai_tools'] === undefined) {
        // Each tool is advertised as `llm.tools.N.tool.json_schema`, holding an
        // OpenAI-style `{type: 'function', function: {...}}` spec serialized to
        // JSON — exactly the $ai_tools shape, so parse and pass through.
        const tools = reassembleIndexedAttributes(props, 'llm.tools.', ['tool.json_schema'], [])
        if (tools) {
            const parsed = tools
                .map((tool) => {
                    const raw = tool['tool.json_schema']
                    if (typeof raw === 'string') {
                        try {
                            return parseJSON(raw)
                        } catch {
                            return raw
                        }
                    }
                    return raw
                })
                .filter((tool) => tool !== undefined)
            if (parsed.length > 0) {
                props['$ai_tools'] = parsed
            }
        }
    }

    // Non-LLM spans (CHAIN, AGENT, RETRIEVER, ...) carry their payload on
    // `input.value` / `output.value`. On generation and embedding events those
    // keys only duplicate the message attributes, so they are dropped either way.
    if (event.event === '$ai_span' || event.event === '$ai_trace') {
        if (props['$ai_input_state'] === undefined && props['input.value'] !== undefined) {
            props['$ai_input_state'] = parseValueAttribute(props['input.value'], props['input.mime_type'])
        }
        if (props['$ai_output_state'] === undefined && props['output.value'] !== undefined) {
            props['$ai_output_state'] = parseValueAttribute(props['output.value'], props['output.mime_type'])
        }
    }
    delete props['input.value']
    delete props['output.value']

    props['$ai_lib'] = 'opentelemetry/openinference'

    for (const key of STRIP_KEYS) {
        delete props[key]
    }
    for (const key of Object.keys(props)) {
        if (STRIP_PREFIXES.some((prefix) => key.startsWith(prefix))) {
            delete props[key]
        }
    }
}

export const openinference: OtelLibraryMiddleware = {
    name: 'openinference',
    // Same acceptance rule as capture: any `openinference.`-prefixed attribute.
    // Spans normally carry `openinference.span.kind`, but capture admits the
    // bare prefix too, so match the wider net rather than one marker key.
    matches: (event) => Object.keys(event.properties ?? {}).some((key) => key.startsWith('openinference.')),
    process,
}
