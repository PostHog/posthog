import { PluginEvent } from '~/plugin-scaffold'

import { parseJSON } from '../../../../utils/json-parse'
import { OtelLibraryMiddleware } from './types'

// Vercel AI SDK attributes to strip after processing. These are all prefixed
// with ai.* and are Vercel-specific, not part of the GenAI semantic conventions.
const STRIP_KEYS = [
    'ai.operationId',
    'ai.telemetry.functionId',
    'ai.model.id',
    'ai.model.provider',
    'ai.settings.maxRetries',
    'ai.settings.maxOutputTokens',
    'ai.usage.promptTokens',
    'ai.usage.completionTokens',
    'ai.response.finishReason',
    'ai.response.id',
    'ai.response.model',
    'ai.response.timestamp',
    'ai.response.providerMetadata',
    'ai.response.avgCompletionTokensPerSecond',
    'ai.response.msToFirstChunk',
    'ai.response.msToFinish',
    'ai.prompt',
    'ai.prompt.tools',
    'ai.prompt.toolChoice',
    'ai.response.toolCalls',
    'ai.value',
    'ai.embedding',
    'ai.values',
    'ai.embeddings',
    'ai.schema',
    'ai.schema.name',
    'ai.schema.description',
    'ai.response.object',
    'ai.settings.output',
    'operation.name',
    'resource.name',
]

function process(event: PluginEvent, next: () => void): void {
    if (!event.properties) {
        return next()
    }
    const props = event.properties

    // Capture opId before next() since STRIP_KEYS deletes it afterward
    const opId = props['ai.operationId']

    // Map ai.prompt.messages → gen_ai.input.messages before the standard mapping
    // runs, so mapOtelAttributes() picks it up as $ai_input.
    if (props['ai.prompt.messages'] !== undefined && props['gen_ai.input.messages'] === undefined) {
        props['gen_ai.input.messages'] = props['ai.prompt.messages']
    }
    delete props['ai.prompt.messages']

    // Build gen_ai.output.messages from ai.response.text so mapOtelAttributes()
    // maps it to $ai_output_choices. We pass the array directly since
    // mapOtelAttributes only parses string values.
    if (props['ai.response.text'] !== undefined && props['gen_ai.output.messages'] === undefined) {
        const text = props['ai.response.text']
        props['gen_ai.output.messages'] = [{ role: 'assistant', content: text }]
    }
    delete props['ai.response.text']

    next()

    // For trace-level spans (top-level generateText/streamText), set input/output state
    const isTopLevel =
        event.event === '$ai_trace' ||
        (typeof opId === 'string' &&
            !opId.endsWith('.doGenerate') &&
            !opId.endsWith('.doStream') &&
            opId !== 'ai.toolCall' &&
            !opId.includes('.doEmbed'))
    if (isTopLevel && event.event !== '$ai_generation') {
        if (props['$ai_input'] !== undefined && props['$ai_input_state'] === undefined) {
            const input = props['$ai_input']
            if (Array.isArray(input)) {
                const userMsg = input.find(
                    (m: Record<string, unknown>) => typeof m === 'object' && m !== null && m.role === 'user'
                )
                if (userMsg) {
                    props['$ai_input_state'] = userMsg
                }
            }
        }
        if (props['$ai_output_choices'] !== undefined && props['$ai_output_state'] === undefined) {
            const output = props['$ai_output_choices']
            if (Array.isArray(output) && output.length > 0) {
                props['$ai_output_state'] = output[output.length - 1]
            }
        }
    }

    // Handle tool call spans
    if (opId === 'ai.toolCall') {
        if (props['ai.toolCall.name'] !== undefined) {
            props['$ai_span_name'] = props['ai.toolCall.name']
        }
        if (props['ai.toolCall.args'] !== undefined) {
            let args = props['ai.toolCall.args']
            if (typeof args === 'string') {
                try {
                    args = parseJSON(args)
                } catch {
                    // Keep original string
                }
            }
            props['$ai_input_state'] = args
        }
        if (props['ai.toolCall.result'] !== undefined) {
            let result = props['ai.toolCall.result']
            if (typeof result === 'string') {
                try {
                    result = parseJSON(result)
                } catch {
                    // Keep original string
                }
            }
            props['$ai_output_state'] = result
        }

        delete props['ai.toolCall.name']
        delete props['ai.toolCall.id']
        delete props['ai.toolCall.args']
        delete props['ai.toolCall.result']
    }

    // Strip Vercel-specific telemetry metadata and request headers
    for (const key of Object.keys(props)) {
        if (key.startsWith('ai.telemetry.metadata.')) {
            delete props[key]
        } else if (key.startsWith('ai.request.headers.')) {
            delete props[key]
        }
    }

    props['$ai_lib'] = 'opentelemetry/vercel-ai'

    for (const key of STRIP_KEYS) {
        delete props[key]
    }
}

const MARKER_KEYS = ['ai.operationId', 'ai.telemetry.functionId']

export const vercelAi: OtelLibraryMiddleware = {
    name: 'vercel-ai',
    matches: (event) => MARKER_KEYS.some((key) => event.properties?.[key] !== undefined),
    process,
}
