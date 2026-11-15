import { parseJSON } from '~/common/utils/json-parse'
import { finiteNumberOrUndefined } from '~/ingestion/pipelines/ai/costs/cost-utils'
import { PluginEvent } from '~/plugin-scaffold'

import { usableStopReason } from './stop-reason'
import { OtelLibraryMiddleware } from './types'

const ATTRIBUTE_PREFIX = 'anthropic.'

const SESSION_ID_KEY = 'anthropic.session.id'
const STOP_REASON_KEYS = ['anthropic.message.stop_reason', 'anthropic.session.turn.stop_reason']
const TOOL_RESULT_KEY = 'anthropic.tool_result.content'

// Kept out of the generic mapping on purpose. Other producers of these attributes can count
// tokens differently, and the cost calculation would then bill them twice.
const RENAMED_ATTRIBUTES: Record<string, string> = {
    'gen_ai.usage.cache_write.input_tokens': '$ai_cache_creation_input_tokens',
    'gen_ai.usage.reasoning.output_tokens': '$ai_reasoning_tokens',
    'gen_ai.request.max_tokens': '$ai_max_tokens',
    'gen_ai.request.stream': '$ai_stream',
}

// Compaction runs before the model, and the span's own usage attributes leave its tokens out.
const COMPACTION_TOKENS: Record<string, string> = {
    'anthropic.usage.compaction.input_tokens': '$ai_input_tokens',
    'anthropic.usage.compaction.output_tokens': '$ai_output_tokens',
}

const CACHE_WRITE_5M_KEY = 'anthropic.usage.cache_creation.ephemeral_5m_input_tokens'
const CACHE_WRITE_1H_KEY = 'anthropic.usage.cache_creation.ephemeral_1h_input_tokens'

const WEB_SEARCH_TOOL_NAME = 'web_search'
// A client tool can also be named web_search. Only calls the provider ran itself carry this id
// prefix, and only those have a per-search fee.
const SERVER_TOOL_CALL_ID_PREFIX = 'srvtoolu_'
const TOOL_CALL_PART_TYPES = new Set(['tool_call', 'server_tool_call'])
const TOOL_RESPONSE_PART_TYPES = new Set(['tool_call_response', 'server_tool_call_response'])

function renameAttributes(props: Record<string, unknown>): void {
    for (const [otelKey, phKey] of Object.entries(RENAMED_ATTRIBUTES)) {
        if (props[otelKey] !== undefined && props[phKey] === undefined) {
            props[phKey] = props[otelKey]
        }
        delete props[otelKey]
    }
}

// The cost calculation bills the breakdown instead of the total when both are present. A request
// that ran several model iterations can report a breakdown that covers only some of them, so the
// breakdown is used only when it adds up to the total. A missing TTL counts as zero.
function mapCacheWriteBreakdown(props: Record<string, unknown>): void {
    if (
        props['$ai_cache_creation_5m_input_tokens'] !== undefined ||
        props['$ai_cache_creation_1h_input_tokens'] !== undefined
    ) {
        return
    }
    const write5m = finiteNumberOrUndefined(props[CACHE_WRITE_5M_KEY])
    const write1h = finiteNumberOrUndefined(props[CACHE_WRITE_1H_KEY])
    if (write5m === undefined && write1h === undefined) {
        return
    }

    const breakdownTotal = (write5m ?? 0) + (write1h ?? 0)
    const total = finiteNumberOrUndefined(props['$ai_cache_creation_input_tokens'])
    if (total !== undefined && total !== breakdownTotal) {
        return
    }
    props['$ai_cache_creation_input_tokens'] = breakdownTotal
    props['$ai_cache_creation_5m_input_tokens'] = write5m ?? 0
    props['$ai_cache_creation_1h_input_tokens'] = write1h ?? 0
    delete props[CACHE_WRITE_5M_KEY]
    delete props[CACHE_WRITE_1H_KEY]
}

function addCompactionTokens(props: Record<string, unknown>): void {
    for (const [compactionKey, phKey] of Object.entries(COMPACTION_TOKENS)) {
        const compactionTokens = finiteNumberOrUndefined(props[compactionKey])
        const reportedTokens = finiteNumberOrUndefined(props[phKey])
        if (compactionTokens !== undefined && compactionTokens > 0 && reportedTokens !== undefined) {
            props[phKey] = reportedTokens + compactionTokens
        }
    }
}

function parseIfJson(value: unknown): unknown {
    if (typeof value !== 'string') {
        return value
    }
    try {
        return parseJSON(value)
    } catch {
        return value
    }
}

function serverWebSearchCallId(part: object): string | undefined {
    if (!('type' in part) || !('name' in part) || !('id' in part)) {
        return undefined
    }
    if (typeof part.type !== 'string' || typeof part.id !== 'string') {
        return undefined
    }
    const isServerWebSearch =
        TOOL_CALL_PART_TYPES.has(part.type) &&
        part.name === WEB_SEARCH_TOOL_NAME &&
        part.id.startsWith(SERVER_TOOL_CALL_ID_PREFIX)
    return isServerWebSearch ? part.id : undefined
}

// A search that returned results reports them as a list. A refused search, for example one past
// the request's search limit, reports an error object and has no fee.
function successfulToolResponseId(part: object): string | undefined {
    if (!('type' in part) || !('id' in part) || !('response' in part)) {
        return undefined
    }
    if (typeof part.type !== 'string' || typeof part.id !== 'string') {
        return undefined
    }
    return TOOL_RESPONSE_PART_TYPES.has(part.type) && Array.isArray(part.response) ? part.id : undefined
}

function countServerWebSearches(outputChoices: unknown): number {
    if (!Array.isArray(outputChoices)) {
        return 0
    }
    const searchIds = new Set<string>()
    const succeededIds = new Set<string>()
    for (const message of outputChoices) {
        if (typeof message !== 'object' || message === null || !('parts' in message) || !Array.isArray(message.parts)) {
            continue
        }
        for (const part of message.parts) {
            if (typeof part !== 'object' || part === null) {
                continue
            }
            const searchId = serverWebSearchCallId(part)
            if (searchId !== undefined) {
                searchIds.add(searchId)
            }
            const succeededId = successfulToolResponseId(part)
            if (succeededId !== undefined) {
                succeededIds.add(succeededId)
            }
        }
    }
    return [...searchIds].filter((id) => succeededIds.has(id)).length
}

function mapToolExecution(props: Record<string, unknown>): void {
    if (props['gen_ai.tool.name'] !== undefined) {
        props['$ai_span_name'] = props['gen_ai.tool.name']
    }
    if (props['gen_ai.tool.call.arguments'] !== undefined && props['$ai_input_state'] === undefined) {
        props['$ai_input_state'] = parseIfJson(props['gen_ai.tool.call.arguments'])
    }
    if (props[TOOL_RESULT_KEY] !== undefined && props['$ai_output_state'] === undefined) {
        props['$ai_output_state'] = parseIfJson(props[TOOL_RESULT_KEY])
    }
    delete props['gen_ai.tool.name']
    delete props['gen_ai.tool.call.arguments']
    delete props[TOOL_RESULT_KEY]
}

function process(event: PluginEvent, next: () => void): void {
    if (!event.properties) {
        return next()
    }
    const props = event.properties

    // The generic mapping strips the operation name, so it must be read first.
    const isToolExecution = props['gen_ai.operation.name'] === 'execute_tool'

    next()

    renameAttributes(props)

    // These spans report input tokens that already include the tokens read from and written to
    // the prompt cache. The cost calculation otherwise assumes the opposite for this provider.
    if (props['$ai_input_tokens'] !== undefined && props['$ai_cache_reporting_exclusive'] === undefined) {
        props['$ai_cache_reporting_exclusive'] = false
    }
    mapCacheWriteBreakdown(props)
    addCompactionTokens(props)

    if (props['$ai_stop_reason'] === undefined) {
        const stopReason = STOP_REASON_KEYS.map((key) => usableStopReason(props[key])).find((r) => r !== undefined)
        if (stopReason !== undefined) {
            props['$ai_stop_reason'] = stopReason
        }
    }
    for (const key of STOP_REASON_KEYS) {
        delete props[key]
    }

    // A session can hold several conversation threads, so it is the wider grouping and takes the
    // session id before the conversation id fallback runs.
    const sessionId = props[SESSION_ID_KEY]
    if (props['$ai_session_id'] === undefined && typeof sessionId === 'string' && sessionId !== '') {
        props['$ai_session_id'] = sessionId
    }
    delete props[SESSION_ID_KEY]

    if (isToolExecution) {
        mapToolExecution(props)
    }

    if (event.event === '$ai_generation' && props['$ai_web_search_count'] === undefined) {
        const webSearches = countServerWebSearches(props['$ai_output_choices'])
        if (webSearches > 0) {
            props['$ai_web_search_count'] = webSearches
        }
    }

    props['$ai_lib'] = 'opentelemetry/anthropic'
}

export const anthropic: OtelLibraryMiddleware = {
    name: 'anthropic',
    matches: (event) => Object.keys(event.properties ?? {}).some((key) => key.startsWith(ATTRIBUTE_PREFIX)),
    process,
}
