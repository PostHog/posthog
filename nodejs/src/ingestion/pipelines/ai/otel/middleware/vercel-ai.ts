import { parseJSON } from '~/common/utils/json-parse'
import { mustAddReasoningCost } from '~/ingestion/pipelines/ai/costs/output-costs'
import { PluginEvent } from '~/plugin-scaffold'

import { promotePosthogCustomMetadata } from './custom-metadata'
import { OtelLibraryMiddleware } from './types'

// Provider-specific and standard attributes to strip after processing.
const STRIP_KEYS = [
    // Vercel AI SDK and Eve-specific
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
    'ai.usage.inputTokenDetails.noCacheTokens',
    'ai.usage.outputTokenDetails.textTokens',
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
    'eve.session.id',
    // Standard GenAI semantic convention attributes not mapped to $ai_* properties
    'gen_ai.request.max_tokens',
    'gen_ai.response.id',
]

const STRING_AI_CONTEXT_KEYS = ['$ai_session_id', '$ai_prompt_name']
const AI_PROMPT_VERSION_KEY = '$ai_prompt_version'
const AI_TELEMETRY_METADATA_PREFIX = 'ai.telemetry.metadata.'
const AI_RUNTIME_CONTEXT_PREFIX = 'ai.settings.context.'
const AI_CONTEXT_PREFIXES = [AI_TELEMETRY_METADATA_PREFIX, AI_RUNTIME_CONTEXT_PREFIX]
const EVE_MARKER_KEYS = ['eve.version', 'eve.session.id']
const EVE_TURN_SPAN_NAME = 'ai.eve.turn'

function isNonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value.length > 0
}

function isPromptVersion(value: unknown): value is string | number {
    return isNonEmptyString(value) || (typeof value === 'number' && Number.isInteger(value) && value > 0)
}

function getAiContextValue(props: Record<string, unknown>, key: string): unknown {
    for (const prefix of AI_CONTEXT_PREFIXES) {
        const value = props[`${prefix}${key}`]
        if (value !== undefined) {
            return value
        }
    }
    return undefined
}

function normalizeEveRuntimeContext(props: Record<string, unknown>): void {
    const eveRuntimeContextPrefix = `${AI_RUNTIME_CONTEXT_PREFIX}eve.`
    for (const key of Object.keys(props)) {
        if (!key.startsWith(eveRuntimeContextPrefix)) {
            continue
        }
        const eveKey = key.slice(AI_RUNTIME_CONTEXT_PREFIX.length)
        props[eveKey] ??= props[key]
        delete props[key]
    }
}

function promotePosthogContext(props: Record<string, unknown>): void {
    for (const prefix of AI_CONTEXT_PREFIXES) {
        promotePosthogCustomMetadata(props, prefix)
    }
}

function stripProcessedContext(props: Record<string, unknown>): void {
    for (const key of Object.keys(props)) {
        if (
            key.startsWith(AI_TELEMETRY_METADATA_PREFIX) ||
            key.startsWith(AI_RUNTIME_CONTEXT_PREFIX) ||
            key.startsWith('ai.request.headers.')
        ) {
            delete props[key]
        }
    }
}

function isEveSpan(props: Record<string, unknown>): boolean {
    return EVE_MARKER_KEYS.some((key) => props[key] !== undefined)
}

function isEveTurnSpan(props: Record<string, unknown>): boolean {
    return (
        isEveSpan(props) &&
        (props['$otel_span_name'] === EVE_TURN_SPAN_NAME || props['$ai_span_name'] === EVE_TURN_SPAN_NAME)
    )
}

// Vercel AI SDK top-level spans (ai.generateText/ai.streamText/ai.*Object) record
// ai.prompt as a JSON object — { system?, prompt?, messages? } — not a bare
// messages array. Flatten it into a messages array so it maps to $ai_input.
// Older SDK versions (and provider-level spans) sent a bare array or raw string,
// which we still accept.
function promptToMessages(prompt: unknown): unknown[] | null {
    if (Array.isArray(prompt)) {
        return prompt
    }
    if (typeof prompt === 'string') {
        return [{ role: 'user', content: prompt }]
    }
    if (prompt !== null && typeof prompt === 'object') {
        const { system, prompt: rawPrompt, messages } = prompt as Record<string, unknown>
        const result: unknown[] = []
        if (isNonEmptyString(system)) {
            result.push({ role: 'system', content: system })
        }
        if (Array.isArray(messages)) {
            result.push(...messages)
        } else if (isNonEmptyString(rawPrompt)) {
            result.push({ role: 'user', content: rawPrompt })
        }
        return result.length > 0 ? result : null
    }
    return null
}

function numericValue(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return value
    }
    if (typeof value === 'string') {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : null
    }
    return null
}

function process(event: PluginEvent, next: () => void): void {
    if (!event.properties) {
        return next()
    }
    const props = event.properties
    normalizeEveRuntimeContext(props)
    const eveSpan = isEveSpan(props)

    // Eve's Workflow parent is filtered before ingestion, so the turn must become the logical trace root.
    if (isEveTurnSpan(props)) {
        delete props['$ai_parent_id']
    }

    // Capture opId before next() since STRIP_KEYS deletes it afterward
    const opId = props['ai.operationId']
    const hasAiSdkV7CacheUsage =
        props['gen_ai.usage.cache_read.input_tokens'] !== undefined ||
        props['gen_ai.usage.cache_creation.input_tokens'] !== undefined ||
        props['ai.usage.inputTokenDetails.noCacheTokens'] !== undefined
    const aiSdkV7TextOutputTokens = props['ai.usage.outputTokenDetails.textTokens']
    const aiSdkV7ReasoningTokens = props['ai.usage.outputTokenDetails.reasoningTokens']
    const hasAiSdkV7ReasoningDetails = aiSdkV7ReasoningTokens !== undefined

    if (props['$ai_cache_reporting_exclusive'] === undefined && hasAiSdkV7CacheUsage) {
        props['$ai_cache_reporting_exclusive'] = false
    }

    // Map ai.prompt.messages → gen_ai.input.messages before the standard mapping
    // runs, so mapOtelAttributes() picks it up as $ai_input. Provider-level spans
    // (doGenerate/doStream) carry ai.prompt.messages, while top-level wrapper
    // spans carry ai.prompt — a { system?, prompt?, messages? } object, a bare
    // messages array, or a raw string depending on the SDK version.
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
        const messages = promptToMessages(prompt)
        if (messages) {
            props['gen_ai.input.messages'] = messages
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

    // Legacy AI SDK telemetry sends the tool catalog as ai.prompt.tools, an
    // array of individually stringified tool definitions. Parse each entry so
    // $ai_tools ends up carrying objects, like the current
    // gen_ai.tool.definitions attribute does.
    if (props['ai.prompt.tools'] !== undefined && props['gen_ai.tool.definitions'] === undefined) {
        const tools = props['ai.prompt.tools']
        if (Array.isArray(tools)) {
            props['gen_ai.tool.definitions'] = tools.map((tool) => {
                if (typeof tool !== 'string') {
                    return tool
                }
                try {
                    return parseJSON(tool)
                } catch {
                    return tool
                }
            })
        }
    }

    // Promote groups before the generic mapper runs so it can parse the JSON value.
    const groupsMetadata = getAiContextValue(props, '$groups')
    if (props['$groups'] === undefined && isNonEmptyString(groupsMetadata)) {
        props['$groups'] = groupsMetadata
    }

    next()

    // For trace-level spans (top-level generateText/streamText), set input/output state.
    // Uses a positive allowlist so new Vercel AI operations default to non-top-level.
    const TOP_LEVEL_OPS = ['ai.generateText', 'ai.streamText', 'ai.generateObject', 'ai.streamObject']
    const isTopLevel = event.event === '$ai_trace' || (typeof opId === 'string' && TOP_LEVEL_OPS.includes(opId))
    if (isTopLevel && event.event !== '$ai_generation') {
        if (props['$ai_input'] !== undefined && props['$ai_input_state'] === undefined) {
            const input = props['$ai_input']
            if (Array.isArray(input)) {
                // Prefer the most recent user turn so multi-turn traces show the
                // current message rather than the start of the conversation.
                const userMsg = input.findLast(
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

    // The functionId represents the whole trace's purpose, so only override the span name for the top-level event
    if (isTopLevel && typeof functionId === 'string' && functionId) {
        props['$ai_span_name'] = functionId
    }

    const posthogDistinctId = getAiContextValue(props, 'posthog_distinct_id')
    if (typeof posthogDistinctId === 'string' && posthogDistinctId) {
        if (props['posthog_distinct_id'] === undefined) {
            props['posthog_distinct_id'] = posthogDistinctId
        }
        event.distinct_id = posthogDistinctId
    }

    for (const aiKey of STRING_AI_CONTEXT_KEYS) {
        const value = getAiContextValue(props, aiKey)
        if (props[aiKey] === undefined && isNonEmptyString(value)) {
            props[aiKey] = value
        }
    }

    const promptVersion = getAiContextValue(props, AI_PROMPT_VERSION_KEY)
    if (props[AI_PROMPT_VERSION_KEY] === undefined && isPromptVersion(promptVersion)) {
        props[AI_PROMPT_VERSION_KEY] = promptVersion
    }

    // Vercel repeats context across provider spans, so only rename the top-level event.
    const spanNameOverride = getAiContextValue(props, '$ai_span_name')
    if (isTopLevel && isNonEmptyString(spanNameOverride)) {
        props['$ai_span_name'] = spanNameOverride
    }

    promotePosthogContext(props)

    stripProcessedContext(props)

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

    if (eveSpan) {
        const eveSessionId = props['eve.session.id']
        if (props['$ai_session_id'] === undefined && isNonEmptyString(eveSessionId)) {
            props['$ai_session_id'] = eveSessionId
        }
    }

    props['$ai_lib'] = 'opentelemetry/vercel-ai'
    props['$ai_framework'] ??= eveSpan ? 'eve' : 'vercel'

    if (props['$ai_reasoning_tokens'] === undefined && aiSdkV7ReasoningTokens !== undefined) {
        props['$ai_reasoning_tokens'] = aiSdkV7ReasoningTokens
    }

    const shouldSplitReasoningTokens =
        typeof props['$ai_model'] === 'string' && mustAddReasoningCost(props['$ai_model'])
    if (props['$ai_text_output_tokens'] === undefined && shouldSplitReasoningTokens) {
        const textOutputTokens = numericValue(aiSdkV7TextOutputTokens)
        if (textOutputTokens !== null) {
            props['$ai_text_output_tokens'] = textOutputTokens
        } else if (hasAiSdkV7ReasoningDetails) {
            const outputTokens = numericValue(props['$ai_output_tokens'])
            const reasoningTokens = numericValue(props['$ai_reasoning_tokens'])
            if (outputTokens !== null && reasoningTokens !== null) {
                props['$ai_text_output_tokens'] = Math.max(0, outputTokens - reasoningTokens)
            }
        }
    }

    for (const key of STRIP_KEYS) {
        delete props[key]
    }
}

const MARKER_KEYS = [
    'ai.operationId',
    'ai.telemetry.functionId',
    ...EVE_MARKER_KEYS,
    ...EVE_MARKER_KEYS.map((key) => `${AI_RUNTIME_CONTEXT_PREFIX}${key}`),
]

export const vercelAi: OtelLibraryMiddleware = {
    name: 'vercel-ai',
    matches: (event) => MARKER_KEYS.some((key) => event.properties?.[key] !== undefined),
    process,
}
