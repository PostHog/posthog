import { PluginEvent } from '~/plugin-scaffold'

import { parseJSON } from '../../../../utils/json-parse'
import { OtelLibraryMiddleware } from './types'

// Vercel AI SDK attributes to strip after processing. Includes both
// Vercel-specific ai.* attributes and standard GenAI semantic convention
// attributes that have already been mapped to $ai_* properties.
const STRIP_KEYS = [
    // Vercel AI SDK specific
    'ai.operationId',
    'ai.telemetry.functionId',
    'ai.model.id',
    'ai.model.provider',
    'ai.settings.maxRetries',
    'ai.settings.maxOutputTokens',
    'ai.settings.output',
    'ai.usage.promptTokens',
    'ai.usage.completionTokens',
    'ai.usage.tokens',
    'ai.response.id',
    'ai.response.model',
    'ai.response.timestamp',
    'ai.response.providerMetadata',
    'ai.response.avgCompletionTokensPerSecond',
    'ai.response.msToFirstChunk',
    'ai.response.msToFinish',
    'ai.response.reasoning',
    'ai.response.object',
    'ai.response.toolCalls',
    'ai.prompt',
    'ai.prompt.tools',
    'ai.prompt.toolChoice',
    'ai.value',
    'ai.embedding',
    'ai.values',
    'ai.embeddings',
    'ai.schema',
    'ai.schema.name',
    'ai.schema.description',
    'operation.name',
    'resource.name',
    // Standard GenAI semantic convention attributes not mapped to $ai_* properties
    'gen_ai.request.max_tokens',
    'gen_ai.response.id',
]

function process(event: PluginEvent, next: () => void): void {
    if (!event.properties) {
        return next()
    }
    const props = event.properties

    // Capture opId before next() since STRIP_KEYS deletes it afterward
    const opId = props['ai.operationId']

    // Map ai.prompt.messages → gen_ai.input.messages before the standard mapping
    // runs, so mapOtelAttributes() picks it up as $ai_input. Provider-level spans
    // (doGenerate/doStream) carry ai.prompt.messages, while top-level wrapper
    // spans carry ai.prompt as a raw string.
    if (props['ai.prompt.messages'] !== undefined && props['gen_ai.input.messages'] === undefined) {
        props['gen_ai.input.messages'] = props['ai.prompt.messages']
    } else if (props['ai.prompt'] !== undefined && props['gen_ai.input.messages'] === undefined) {
        let prompt = props['ai.prompt']
        if (typeof prompt === 'string') {
            try {
                prompt = parseJSON(prompt)
            } catch {
                // Keep original string
            }
        }
        if (Array.isArray(prompt)) {
            props['gen_ai.input.messages'] = prompt
        } else if (typeof prompt === 'string') {
            props['gen_ai.input.messages'] = [{ role: 'user', content: prompt }]
        }
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

    // For trace-level spans (top-level generateText/streamText), set input/output state.
    // Uses a positive allowlist so new Vercel AI operations default to non-top-level.
    const TOP_LEVEL_OPS = ['ai.generateText', 'ai.streamText', 'ai.generateObject', 'ai.streamObject']
    const isTopLevel = event.event === '$ai_trace' || (typeof opId === 'string' && TOP_LEVEL_OPS.includes(opId))
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

    const functionId = props['ai.telemetry.functionId']
    if (props['functionId'] === undefined && typeof functionId === 'string' && functionId) {
        props['functionId'] = functionId
    }

    const posthogDistinctId = props['ai.telemetry.metadata.posthog_distinct_id']
    if (typeof posthogDistinctId === 'string' && posthogDistinctId) {
        if (props['posthog_distinct_id'] === undefined) {
            props['posthog_distinct_id'] = posthogDistinctId
        }
        event.distinct_id = posthogDistinctId
    }

    const aiSessionId = props['ai.telemetry.metadata.$ai_session_id']
    if (props['$ai_session_id'] === undefined && typeof aiSessionId === 'string' && aiSessionId) {
        props['$ai_session_id'] = aiSessionId
    }

    // Strip Vercel-specific telemetry metadata and request headers after preserving
    // the PostHog identifiers we rely on for event linkage and session grouping.
    for (const key of Object.keys(props)) {
        if (key.startsWith('ai.telemetry.metadata.')) {
            delete props[key]
        } else if (key.startsWith('ai.request.headers.')) {
            delete props[key]
        }
    }

    // Map finish reason to $ai_stop_reason before stripping
    if (props['$ai_stop_reason'] === undefined) {
        const vercelReason = props['ai.response.finishReason']
        const genAiReasons = props['gen_ai.response.finish_reasons']
        if (vercelReason !== undefined) {
            props['$ai_stop_reason'] = vercelReason
        } else if (Array.isArray(genAiReasons) && genAiReasons.length > 0) {
            props['$ai_stop_reason'] = genAiReasons[0]
        }
    }
    delete props['ai.response.finishReason']
    delete props['gen_ai.response.finish_reasons']

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
