import * as PartialJSON from 'partial-json'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { isObject, isString } from 'lib/utils/guards'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import type { SpanAggregation } from './aiObservabilityTraceDataLogic'
import { EVALUATION_SUMMARY_MAX_RUNS } from './evaluations/constants'
import type { EvaluationOutputType, EvaluationRun, EvaluationType } from './evaluations/types'
import {
    AnthropicDocumentMessage,
    AnthropicImageMessage,
    AnthropicToolCallMessage,
    AnthropicToolResultMessage,
    CompatMessage,
    GeminiAudioMessage,
    GeminiDocumentMessage,
    GeminiImageMessage,
    OpenAIAudioMessage,
    OpenAIFileMessage,
    OpenAIImageURLMessage,
    OpenAIResponsesBuiltinToolCall,
    OpenAIResponsesFunctionCall,
    OpenAIResponsesFunctionCallOutput,
    StringContentObject,
    TextContentItem,
    VercelSDKInputTextMessage,
    VercelSDKTextMessage,
    VercelSDKToolCallFunctionMessage,
    VercelSDKToolCallMessage,
    VercelSDKToolCallToolNameMessage,
    VercelSDKToolResultMessage,
} from './types'

export interface PagedSearchOrderFilters {
    page: number
    search: string
    order_by: string
}

// Runs an async worker across `items` with at most `limit` promises in flight.
// Intended for lazy loaders that otherwise fan out enough parallel requests to
// starve the browser's per-origin connection pool.
export async function runWithConcurrency<T>(
    items: T[],
    limit: number,
    worker: (item: T) => Promise<void>
): Promise<void> {
    if (items.length === 0) {
        return
    }
    let cursor = 0
    const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
        while (cursor < items.length) {
            const index = cursor++
            await worker(items[index])
        }
    })
    await Promise.all(runners)
}

export interface SanitizeTraceUrlSearchParamsOptions {
    removeSearch?: boolean
}

export function sanitizeTraceUrlSearchParams(
    searchParams: Record<string, unknown>,
    options: SanitizeTraceUrlSearchParamsOptions = {}
): Record<string, unknown> {
    const sanitizedSearchParams = { ...searchParams }

    delete sanitizedSearchParams.event
    delete sanitizedSearchParams.timestamp
    delete sanitizedSearchParams.exception_ts
    delete sanitizedSearchParams.line
    delete sanitizedSearchParams.tab
    delete sanitizedSearchParams.back_to
    delete sanitizedSearchParams.msg

    if (options.removeSearch) {
        delete sanitizedSearchParams.search
    }

    return sanitizedSearchParams
}

export function cleanPagedSearchOrderParams(
    filters: PagedSearchOrderFilters,
    defaultOrderBy: string = '-created_at'
): Record<string, unknown> {
    return {
        page: filters.page === 1 ? undefined : filters.page,
        search: filters.search || undefined,
        order_by: filters.order_by === defaultOrderBy ? undefined : filters.order_by,
    }
}

function formatUsage(inputTokens: number, outputTokens?: number | null): string | null {
    return `${inputTokens} → ${outputTokens || 0} (∑ ${inputTokens + (outputTokens || 0)})`
}

export function formatLLMUsage(
    trace_or_event_or_aggregation: LLMTrace | LLMTraceEvent | SpanAggregation
): string | null {
    // Handle SpanAggregation
    if (
        'totalCost' in trace_or_event_or_aggregation &&
        'totalLatency' in trace_or_event_or_aggregation &&
        'hasGenerationChildren' in trace_or_event_or_aggregation
    ) {
        const aggregation = trace_or_event_or_aggregation as SpanAggregation
        return formatUsage(aggregation.inputTokens || 0, aggregation.outputTokens)
    }

    // Handle LLMTraceEvent
    if ('properties' in trace_or_event_or_aggregation) {
        const event = trace_or_event_or_aggregation as LLMTraceEvent
        if (typeof event.properties.$ai_input_tokens === 'number') {
            return formatUsage(event.properties.$ai_input_tokens, event.properties.$ai_output_tokens)
        }
    }

    // Handle LLMTrace
    const trace = trace_or_event_or_aggregation as LLMTrace
    if (typeof trace.inputTokens === 'number') {
        return formatUsage(trace.inputTokens, trace.outputTokens)
    }

    return null
}

export const LLM_TRACES_PAGE_SIZE = 50

export const LATENCY_MINUTES_DISPLAY_THRESHOLD_SECONDS = 90

export function formatLLMLatency(latency: number, showMinutes?: boolean): string {
    const roundedLatency = Math.round(latency * 100) / 100
    if (showMinutes && latency > LATENCY_MINUTES_DISPLAY_THRESHOLD_SECONDS) {
        const minutes = (latency / 60).toFixed(2)
        return `${roundedLatency} s (${minutes} m)`
    }
    return `${roundedLatency} s`
}

export interface CostContext {
    inputCost?: number
    outputCost?: number
    requestCost?: number
    webSearchCost?: number
    totalCost: number
}

export function costContextFromProperties(props: Record<string, any>): CostContext | undefined {
    if (typeof props.$ai_total_cost_usd !== 'number') {
        return undefined
    }
    return {
        inputCost: props.$ai_input_cost_usd,
        outputCost: props.$ai_output_cost_usd,
        requestCost: props.$ai_request_cost_usd,
        webSearchCost: props.$ai_web_search_cost_usd,
        totalCost: props.$ai_total_cost_usd,
    }
}

export function costContextFromTrace(
    trace: Pick<LLMTrace, 'inputCost' | 'outputCost' | 'requestCost' | 'webSearchCost' | 'totalCost'>
): CostContext | undefined {
    if (typeof trace.totalCost !== 'number') {
        return undefined
    }
    return {
        inputCost: trace.inputCost,
        outputCost: trace.outputCost,
        requestCost: trace.requestCost,
        webSearchCost: trace.webSearchCost,
        totalCost: trace.totalCost,
    }
}

export function hasCostBreakdown(ctx: CostContext): boolean {
    return (
        typeof ctx.inputCost === 'number' ||
        typeof ctx.outputCost === 'number' ||
        (typeof ctx.requestCost === 'number' && ctx.requestCost > 0) ||
        (typeof ctx.webSearchCost === 'number' && ctx.webSearchCost > 0)
    )
}

const usdFormatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
})

export function formatLLMCost(cost: number): string {
    return usdFormatter.format(cost)
}

export function formatTokens(tokens: number): string {
    if (tokens >= 1000000) {
        return `${(tokens / 1000000).toFixed(1)}M`
    }
    if (tokens >= 1000) {
        return `${(tokens / 1000).toFixed(1)}k`
    }
    return tokens.toFixed(0)
}

/**
 * Defensive narrowing for values pulled out of `LLMTraceEvent.properties` (typed
 * as `Record<string, any>`). Returns the value when it's a string, otherwise
 * `undefined` — safer than `as string | undefined` which silently lets numbers
 * or objects through. Use this any time a `$ai_*` property is documented as a
 * string by convention but the runtime data could vary.
 */
export function asString(value: unknown): string | undefined {
    return isString(value) ? value : undefined
}

/**
 * Reads the input payload from an event's properties.
 * - `$ai_input`: emitted by every SDK integration on `$ai_generation`
 *   (OpenAI, Anthropic, Gemini, and the framework wrappers).
 * - `$ai_input_state`: emitted by framework wrappers (LangChain, OpenAI Agents,
 *   Claude Agent SDK) on `$ai_span` events that wrap a non-generation step.
 */
export function readAiInput(properties: Record<string, any>): unknown {
    return properties.$ai_input ?? properties.$ai_input_state
}

/**
 * Reads the output payload from an event's properties.
 * - `$ai_output_choices`: emitted by every SDK integration on `$ai_generation`.
 * - `$ai_output_state`: emitted by framework wrappers (LangChain, OpenAI Agents,
 *   Claude Agent SDK) on `$ai_span` events.
 * - `$ai_output`: kept as a defensive fallback for events that the ingestion
 *   pipeline treats as containing a heavy output payload
 */
export function readAiOutput(properties: Record<string, any>): unknown {
    return properties.$ai_output_choices ?? properties.$ai_output_state ?? properties.$ai_output
}

export function eventLabel(event: LLMTraceEvent): string {
    return asString(event.properties.$ai_span_name) || asString(event.properties.$ai_model) || event.event
}

const TRACE_STEP_EVENT_TYPES = new Set(['$ai_generation', '$ai_span', '$ai_embedding'])

export function getTraceStepCount(trace: Partial<Pick<LLMTrace, 'events'>>): number {
    return trace.events?.filter((event) => TRACE_STEP_EVENT_TYPES.has(event.event)).length ?? 0
}

export function formatAiErrorForDisplay(value: unknown): string {
    if (typeof value === 'string') {
        return value || 'Unknown error'
    }
    if (value == null) {
        return 'Unknown error'
    }
    try {
        return JSON.stringify(value)
    } catch {
        return String(value)
    }
}

export function formatErrorRate(errorRate: number): string {
    const percentage = errorRate * 100
    if (percentage === 0) {
        return '0%'
    }
    if (percentage < 0.1) {
        return '<0.1%'
    }
    if (percentage < 1) {
        return `${percentage.toFixed(1)}%`
    }
    return `${Math.round(percentage)}%`
}

export function isLLMEvent(item: LLMTrace | LLMTraceEvent): item is LLMTraceEvent {
    return 'properties' in item
}

/**
 * Checks if the item is a trace-level object (LLMTrace) rather than an individual event.
 * This is the inverse of isLLMEvent and provides semantic clarity when checking for traces.
 */
export function isTraceLevel(item: LLMTrace | LLMTraceEvent): item is LLMTrace {
    return !isLLMEvent(item)
}

function normalizeSessionId(value: unknown): string | null {
    return typeof value === 'string' && value.length > 0 ? value : null
}

function sessionIdFromEvents(events?: LLMTraceEvent[] | null): string | null {
    if (!events || events.length === 0) {
        return null
    }

    const uniqueSessionIds = events.reduce((acc, current) => {
        const candidate = normalizeSessionId(current.properties?.$session_id)
        if (candidate) {
            acc.add(candidate)
        }
        return acc
    }, new Set<string>())

    if (uniqueSessionIds.size !== 1) {
        return null
    }

    return Array.from(uniqueSessionIds)[0]
}

export function getSessionID(event: LLMTrace | LLMTraceEvent, childEvents?: LLMTraceEvent[]): string | null {
    if (isLLMEvent(event)) {
        if (event.event === '$ai_trace') {
            const directSessionId = normalizeSessionId(event.properties?.$session_id)

            return directSessionId ?? sessionIdFromEvents(childEvents)
        }

        return normalizeSessionId(event.properties?.$session_id)
    }

    return sessionIdFromEvents(childEvents ?? event.events)
}

export function getEventType(event: LLMTrace | LLMTraceEvent): string {
    if (isLLMEvent(event)) {
        switch (event.event) {
            case '$ai_generation':
                return 'generation'
            case '$ai_embedding':
                return 'embedding'
            case '$ai_trace':
                return 'trace'
            default:
                return 'span'
        }
    }
    return 'trace'
}

export function getRecordingStatus(event: LLMTrace | LLMTraceEvent): string | null {
    if (isLLMEvent(event)) {
        return event.properties.$recording_status || null
    }

    return event.events.find((e) => e.properties.$recording_status !== null)?.properties.$recording_status || null
}

export function isTextContentItem(item: unknown): item is TextContentItem {
    return !!item && typeof item === 'object' && 'type' in item && item.type === 'text' && 'text' in item
}

export function hasStringContentField(value: unknown): value is StringContentObject {
    return typeof value === 'object' && value !== null && 'content' in value && isString(value.content)
}

// Returns the user-visible string from a content part
export function extractTextContent(item: unknown): string | undefined {
    if (typeof item === 'string') {
        return item
    }
    if (isTextContentItem(item)) {
        return item.text
    }
    if (isVercelSDKTextMessage(item)) {
        return item.content
    }
    if (isVercelSDKInputTextMessage(item)) {
        return item.text
    }
    return undefined
}

// Pulls the user-visible text out of a whole message. Walks a content array (joining
// per-part text), falls back to the `{type, content: string}` legacy wrapper, and
// otherwise returns '' (caller decides what to do with an empty string).
export function extractText(message: CompatMessage): string {
    const content = message.content
    if (typeof content === 'string') {
        return content
    }
    if (Array.isArray(content)) {
        const parts: string[] = []
        for (const part of content) {
            const text = extractTextContent(part)
            if (text !== undefined) {
                parts.push(text)
            }
        }
        return parts.join('\n')
    }
    if (hasStringContentField(content)) {
        return content.content
    }
    return ''
}

// Like `extractText`, but with one extra fallback for the custom function-shape
// tool-result user message (`{role:'user', content:[{type:'function', tool_name, content}]}`).
export function extractInternalContent(message: CompatMessage): string {
    const text = extractText(message)
    if (text.length > 0) {
        return text
    }
    if (Array.isArray(message.content)) {
        return message.content
            .map((p) => (isObject(p) && isString(p.content) ? p.content : ''))
            .filter(Boolean)
            .join('\n')
    }
    return ''
}

export function isAnthropicToolCallMessage(output: unknown): output is AnthropicToolCallMessage {
    return !!output && typeof output === 'object' && 'type' in output && output.type === 'tool_use'
}

// There are more tags that point to an internal-only message, but these are the most common
// ones, i.e. the ones we can most confidently hide by default.
const INTERNAL_TAG_ALLOWLIST: ReadonlySet<string> = new Set([
    'system-reminder',
    'system_reminder',
    'system_reminder_message',
    'attached_context',
    'voice_mode',
])

// Regex for the case where an entire message body consists of exactly one balanced XML wrapper.
// We don't accept content that contains multiple top-level wrappers nor leading/trailing text
const INTERNAL_WRAPPER_REGEX = /^\s*<([a-z][a-z0-9_-]*)>[\s\S]*?<\/\1>\s*$/

// Reduces content to a single text body (flat string, single typed-parts text part,
// or legacy `{content: string}`); returns `undefined` for multi-part / unknown shapes.
function extractSoleTextContent(content: CompatMessage['content']): string | undefined {
    if (typeof content === 'string') {
        return content
    }
    if (Array.isArray(content)) {
        if (content.length !== 1) {
            return undefined
        }
        return extractTextContent(content[0])
    }
    if (hasStringContentField(content)) {
        return content.content
    }
    return undefined
}

// Returns the matched internal tag iff `message` is a user-role message whose entire
// content is one balanced wrapper from `INTERNAL_TAG_ALLOWLIST` (e.g.
// `<system_reminder>foo</system_reminder>`)
export function getInternalTagName(message: CompatMessage): string | undefined {
    if (message.role !== 'user') {
        return undefined
    }
    const body = extractSoleTextContent(message.content)
    if (!body) {
        return undefined
    }
    const match = INTERNAL_WRAPPER_REGEX.exec(body)
    if (!match) {
        return undefined
    }
    const tag = match[1]
    return INTERNAL_TAG_ALLOWLIST.has(tag) ? tag : undefined
}

export function isInternalTagMessage(message: CompatMessage): boolean {
    return getInternalTagName(message) !== undefined
}

// Matches tool-result-shaped content {type: 'function', tool_name: string, content: ...}`
// with NO nested `function` object to distinguish from a tool call
function isCustomFunctionToolResult(item: unknown): boolean {
    return isObject(item) && item.type === 'function' && isString(item.tool_name) && !isObject(item.function)
}

export function isToolResult(item: unknown): boolean {
    return (
        isAnthropicToolResultMessage(item) ||
        isVercelSDKToolResultMessage(item) ||
        isOpenAIResponsesFunctionCallOutput(item) ||
        isCustomFunctionToolResult(item)
    )
}

// A user-role message whose content is exclusively tool-results is framework-emitted
// noise (the user did not write it, their agent appended tool responses into the
// conversation history).
export function isInternalToolResultUserMessage(message: CompatMessage): boolean {
    if (message.role !== 'user') {
        return false
    }
    const { content } = message
    if (!Array.isArray(content) || content.length === 0) {
        return false
    }
    return content.every(isToolResult)
}

export function isToolStepItem(item: unknown): boolean {
    if (
        isAnthropicToolCallMessage(item) ||
        isAnthropicToolResultMessage(item) ||
        isVercelSDKToolCallMessage(item) ||
        isVercelSDKToolResultMessage(item) ||
        isOpenAIResponsesFunctionCall(item) ||
        isOpenAIResponsesBuiltinToolCall(item)
    ) {
        return true
    }
    return (
        typeof item === 'object' &&
        item !== null &&
        'type' in item &&
        item.type === 'function' &&
        'function' in item &&
        typeof item.function === 'object' &&
        item.function !== null
    )
}

export function isAnthropicToolResultMessage(output: unknown): output is AnthropicToolResultMessage {
    return !!output && typeof output === 'object' && 'type' in output && output.type === 'tool_result'
}

// OpenAI Responses API type guards
const OPENAI_RESPONSES_BUILTIN_TOOL_TYPES = new Set([
    'web_search_call',
    'code_interpreter_call',
    'image_generation_call',
    'mcp_call',
    'file_search_call',
    'computer_call',
])

export function isOpenAIResponsesFunctionCall(input: unknown): input is OpenAIResponsesFunctionCall {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'function_call' &&
        'name' in input &&
        'call_id' in input
    )
}

export function isOpenAIResponsesFunctionCallOutput(input: unknown): input is OpenAIResponsesFunctionCallOutput {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'function_call_output' &&
        'call_id' in input &&
        'output' in input
    )
}

export function isOpenAIResponsesBuiltinToolCall(input: unknown): input is OpenAIResponsesBuiltinToolCall {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        typeof input.type === 'string' &&
        OPENAI_RESPONSES_BUILTIN_TOOL_TYPES.has(input.type)
    )
}

export function isVercelSDKTextMessage(input: unknown): input is VercelSDKTextMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'text' &&
        'content' in input &&
        typeof input.content === 'string'
    )
}

export function isVercelSDKInputTextMessage(input: unknown): input is VercelSDKInputTextMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'input_text' &&
        'text' in input &&
        typeof input.text === 'string'
    )
}

function isVercelSDKToolCallFunctionMessage(input: unknown): input is VercelSDKToolCallFunctionMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'tool-call' &&
        'function' in input &&
        typeof input.function === 'object' &&
        input.function !== null
    )
}

function isVercelSDKToolCallToolNameMessage(input: unknown): input is VercelSDKToolCallToolNameMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'tool-call' &&
        'toolName' in input &&
        typeof input.toolName === 'string' &&
        !('function' in input && typeof input.function === 'object' && input.function !== null)
    )
}

export function isVercelSDKToolCallMessage(input: unknown): input is VercelSDKToolCallMessage {
    return isVercelSDKToolCallFunctionMessage(input) || isVercelSDKToolCallToolNameMessage(input)
}

export function isVercelSDKToolResultMessage(input: unknown): input is VercelSDKToolResultMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'tool-result' &&
        'toolName' in input &&
        typeof input.toolName === 'string'
    )
}

export function isOpenAIImageURLMessage(input: unknown): input is OpenAIImageURLMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'image_url' &&
        'image_url' in input &&
        typeof input.image_url === 'object' &&
        input.image_url !== null &&
        'url' in input.image_url &&
        typeof input.image_url.url === 'string'
    )
}

export function isOpenAIFileMessage(input: unknown): input is OpenAIFileMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'file' &&
        'file' in input &&
        typeof input.file === 'object' &&
        input.file !== null &&
        'file_data' in input.file &&
        'filename' in input.file &&
        typeof input.file.file_data === 'string' &&
        typeof input.file.filename === 'string'
    )
}

export function isOpenAIAudioMessage(input: unknown): input is OpenAIAudioMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'audio' &&
        'data' in input &&
        typeof input.data === 'string'
    )
}

export function isAnthropicImageMessage(input: unknown): input is AnthropicImageMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'image' &&
        'source' in input &&
        typeof input.source === 'object' &&
        input.source !== null &&
        'type' in input.source &&
        input.source.type === 'base64' &&
        'data' in input.source &&
        'media_type' in input.source &&
        typeof input.source.data === 'string' &&
        typeof input.source.media_type === 'string'
    )
}

export function isAnthropicDocumentMessage(input: unknown): input is AnthropicDocumentMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'document' &&
        'source' in input &&
        typeof input.source === 'object' &&
        input.source !== null &&
        'type' in input.source &&
        input.source.type === 'base64' &&
        'data' in input.source &&
        'media_type' in input.source &&
        typeof input.source.data === 'string' &&
        typeof input.source.media_type === 'string'
    )
}

/**
 * Extracts inline data from Gemini messages, supporting both snake_case (Python SDK)
 * and camelCase (Node SDK) property naming conventions.
 */
export function getGeminiInlineData(input: unknown): { data: string; mime_type: string } | null {
    if (!input || typeof input !== 'object') {
        return null
    }

    // Check snake_case first (Python SDK)
    if ('inline_data' in input && typeof input.inline_data === 'object' && input.inline_data !== null) {
        const d = input.inline_data as Record<string, unknown>
        const data = d.data
        const mimeType = d.mime_type ?? d.mimeType
        if (typeof data === 'string' && typeof mimeType === 'string') {
            return { data, mime_type: mimeType }
        }
    }

    // Check camelCase (Node SDK)
    if ('inlineData' in input && typeof input.inlineData === 'object' && input.inlineData !== null) {
        const d = input.inlineData as Record<string, unknown>
        const data = d.data
        const mimeType = d.mimeType ?? d.mime_type
        if (typeof data === 'string' && typeof mimeType === 'string') {
            return { data, mime_type: mimeType }
        }
    }

    return null
}

export function isGeminiImageMessage(input: unknown): input is GeminiImageMessage {
    if (!input || typeof input !== 'object' || !('type' in input) || input.type !== 'image') {
        return false
    }
    const inlineData = getGeminiInlineData(input)
    return inlineData !== null && inlineData.mime_type.startsWith('image/')
}

export function isGeminiDocumentMessage(input: unknown): input is GeminiDocumentMessage {
    if (!input || typeof input !== 'object' || !('type' in input)) {
        return false
    }
    const inlineData = getGeminiInlineData(input)
    if (!inlineData) {
        return false
    }
    // Accept explicit 'document' type
    if (input.type === 'document') {
        return true
    }
    // Also accept 'image' type if MIME is not an image (SDK misdetection of PDFs)
    if (input.type === 'image' && !inlineData.mime_type.startsWith('image/')) {
        return true
    }
    return false
}

export function isGeminiAudioMessage(input: unknown): input is GeminiAudioMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'audio' &&
        'data' in input &&
        'mime_type' in input &&
        typeof input.data === 'string' &&
        typeof input.mime_type === 'string'
    )
}

interface OTelPart {
    type: string
    [key: string]: unknown
}

interface OTelPartsMessage {
    role: string
    parts: OTelPart[]
    [key: string]: unknown
}

export function isOTelPartsMessage(input: unknown): input is OTelPartsMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'role' in input &&
        typeof input.role === 'string' &&
        'parts' in input &&
        Array.isArray(input.parts)
    )
}

export const roleMap: Record<string, string> = {
    user: 'user',
    human: 'user',

    assistant: 'assistant',
    model: 'assistant',
    ai: 'assistant',
    bot: 'assistant',

    system: 'system',
    instructions: 'system',
    context: 'system',
}

export function normalizeRole(rawRole: unknown, fallback: string): string {
    if (typeof rawRole !== 'string') {
        return fallback
    }
    const lowercased = rawRole.toLowerCase()
    return roleMap[lowercased] || lowercased
}

// Synthetic role used to surface the `$ai_tools` payload as a pseudo-message
export const AVAILABLE_TOOLS_ROLE = 'available tools'

export const INTERNAL_THINKING_ROLE = 'assistant (thinking)'
export const INTERNAL_TOOL_RESULT_ROLE = 'assistant (tool result)'

const JSON_PREVIEW_LENGTH = 300

// We are deliberately cutting off the JSON instead of the parsed final content
// because we will soon be sending an actual truncated version of the field
// through a materialized column. This forces us to handle partial JSON.
function simulateNaiveTruncation(raw: unknown): string {
    const jsonStr = typeof raw === 'string' ? raw : JSON.stringify(raw)
    return jsonStr.slice(0, JSON_PREVIEW_LENGTH)
}

export function parsePartialJSON(json: string): unknown {
    const flags = PartialJSON.STR | PartialJSON.OBJ | PartialJSON.ARR
    return PartialJSON.parse(json, flags)
}

export function isEmptyJSONStructure(value: unknown): boolean {
    return (
        (Array.isArray(value) && value.length === 0) ||
        (isObject(value) && Object.keys(value as Record<string, unknown>).length === 0)
    )
}

export type ToolArgumentsForDisplay =
    | { kind: 'empty' }
    | { kind: 'parsed'; value: object }
    | { kind: 'raw'; value: string }

/**
 * Tool-call arguments arrive in a few shapes: a JSON-stringified string (raw OpenAI),
 * a parsed object (post-normalization or hand-authored), null/undefined (no args),
 * or an empty container. Normalizes them into a tagged union for rendering.
 */
export function parseToolArgumentsForDisplay(rawArgs: unknown): ToolArgumentsForDisplay {
    if (rawArgs === null || rawArgs === undefined || rawArgs === '') {
        return { kind: 'empty' }
    }
    if (typeof rawArgs === 'string') {
        // Treat literal empty containers as intentional "no args". Anything else that
        // happens to parse to an empty object (e.g. partial-json salvaging broken input)
        // falls through to raw, so the user still sees what they sent.
        const trimmed = rawArgs.trim()
        if (trimmed === '{}' || trimmed === '[]') {
            return { kind: 'empty' }
        }
        try {
            const parsed = parsePartialJSON(rawArgs)
            if (typeof parsed === 'object' && parsed !== null && !isEmptyJSONStructure(parsed)) {
                return { kind: 'parsed', value: parsed }
            }
            return { kind: 'raw', value: rawArgs }
        } catch {
            return { kind: 'raw', value: rawArgs }
        }
    }
    if (typeof rawArgs === 'object') {
        if (isEmptyJSONStructure(rawArgs)) {
            return { kind: 'empty' }
        }
        return { kind: 'parsed', value: rawArgs as object }
    }
    return { kind: 'raw', value: String(rawArgs) }
}

export function parseJSONPreview(raw: unknown): unknown {
    const truncated = simulateNaiveTruncation(raw)
    return parsePartialJSON(truncated)
}

// `JSON.stringify` throws on circular references and BigInt values. When rendering LLM trace data
// in the UI we don't want a malformed payload to crash the component, so wrap it in try/catch with
// a `String(value)` fallback that always produces something.
export function safeStringify(value: unknown, indent: number = 2): string {
    try {
        return JSON.stringify(value, null, indent) ?? String(value)
    } catch {
        return String(value)
    }
}

export function removeMilliseconds(timestamp: string): string {
    return dayjs(timestamp).utc().format('YYYY-MM-DDTHH:mm:ss[Z]')
}

export function getTraceTimestamp(timestamp: string): string {
    return dayjs(timestamp).utc().subtract(5, 'minutes').format('YYYY-MM-DDTHH:mm:ss[Z]')
}

export function getSessionStartTimestamp(timestamp: string): string {
    return dayjs(timestamp).utc().subtract(24, 'hours').format('YYYY-MM-DDTHH:mm:ss[Z]')
}

export function formatLLMEventTitle(event: LLMTrace | LLMTraceEvent): string {
    if (isLLMEvent(event)) {
        const spanName = asString(event.properties.$ai_span_name)

        if (event.event === '$ai_generation') {
            if (spanName) {
                return spanName
            }
            const title = asString(event.properties.$ai_model) || 'Generation'
            const provider = asString(event.properties.$ai_provider)
            return provider ? `${title} (${provider})` : title
        }

        if (event.event === '$ai_embedding') {
            if (spanName) {
                return spanName
            }
            const title = asString(event.properties.$ai_model) || 'Embedding'
            const provider = asString(event.properties.$ai_provider)
            return provider ? `${title} (${provider})` : title
        }

        return spanName ?? 'Span'
    }

    return event.traceName ?? 'Trace'
}

export function formatModelRowLabel(event: LLMTrace | LLMTraceEvent): string | null {
    if (!isLLMEvent(event) || event.event !== '$ai_generation') {
        return null
    }
    // if we don't have a span name, we don't want to render the model row as its covered by the event title
    if (!asString(event.properties.$ai_span_name)) {
        return null
    }
    const model = asString(event.properties.$ai_model)
    const provider = asString(event.properties.$ai_provider)
    if (model && provider) {
        return `${model} (${provider})`
    }
    return model || provider || null
}

/**
 * Lightweight XML-ish content detector for UI toggles.
 * - NOTE: Scans only the first 2KB for signals (to avoid performance issues with regex)
 */
export function looksLikeXml(input: unknown): boolean {
    if (typeof input !== 'string') {
        return false
    }

    const sampleLimit = 2048
    const sample = input.length > sampleLimit ? input.slice(0, sampleLimit) : input

    if (sample.indexOf('<') === -1 || sample.indexOf('>') === -1) {
        return false
    }

    if (sample.includes('</') || sample.includes('/>') || sample.includes('<?xml') || sample.includes('<!DOCTYPE')) {
        return true
    }

    const lt = sample.indexOf('<')
    const next = sample[lt + 1]
    const isNameStart =
        !!next && ((next >= 'A' && next <= 'Z') || (next >= 'a' && next <= 'z') || next === '_' || next === ':')
    return isNameStart
}

/**
 * Formats an ID for display by truncating it to the first and last 4 characters:
 * `1234567890` -> `1234...7890`
 * @param value - The string to format.
 * @returns The formatted string.
 */
export function truncateValue(value: unknown): string {
    if (value === null || value === undefined) {
        return '-'
    }

    const stringValue = String(value)

    if (stringValue.length <= 12) {
        return stringValue
    }

    return stringValue.slice(0, 4) + '...' + stringValue.slice(-4)
}

type RawEvaluationRunRow = [
    id: string,
    timestamp: string,
    evaluation_id: string,
    evaluation_name: string | null,
    generation_id: string,
    trace_id: string,
    result: boolean | string | null,
    reasoning: string | null,
    applicable: boolean | string | null,
    evaluation_type: string | null,
    result_type: string | null,
    sentiment_label: string | null,
    sentiment_score: number | string | null,
]

export function normalizeEvaluationType(value: unknown): EvaluationType | undefined {
    if (value === 'llm_judge' || value === 'hog' || value === 'sentiment') {
        return value
    }
    return undefined
}

export function normalizeEvaluationOutputType(value: unknown): EvaluationOutputType | undefined {
    if (value === 'boolean' || value === 'sentiment') {
        return value
    }
    return undefined
}

export function normalizeOptionalNumber(value: unknown): number | null {
    if (value === null || value === undefined) {
        return null
    }
    const parsed = typeof value === 'number' ? value : Number(value)
    return Number.isFinite(parsed) ? parsed : null
}

export function isExplicitEvaluationPass(value: unknown): boolean {
    return value === true || value === 'true' || value === 'True' || value === '1'
}

function isExplicitEvaluationNotApplicable(value: unknown): boolean {
    return value === false || value === 'false'
}

function normalizeEvaluationApplicable(value: unknown): boolean | undefined {
    if (value === null || value === undefined) {
        return undefined
    }
    return isExplicitEvaluationPass(value)
}

export interface NormalizedEvaluationResultProperties {
    rawResult: unknown
    rawApplicable?: unknown
    rawEvaluationType?: unknown
    rawResultType?: unknown
    rawSentimentLabel?: unknown
    rawSentimentScore?: unknown
}

export function normalizeEvaluationResultProperties({
    rawResult,
    rawApplicable,
    rawEvaluationType,
    rawResultType,
    rawSentimentLabel,
    rawSentimentScore,
}: NormalizedEvaluationResultProperties): Pick<
    EvaluationRun,
    'evaluation_type' | 'result_type' | 'result' | 'sentiment_label' | 'sentiment_score' | 'applicable'
> {
    const evaluationType = normalizeEvaluationType(rawEvaluationType)
    const sentimentLabel =
        typeof rawSentimentLabel === 'string' && rawSentimentLabel.length > 0 ? rawSentimentLabel : null
    const resultType =
        normalizeEvaluationOutputType(rawResultType) ??
        (evaluationType === 'sentiment' || sentimentLabel ? 'sentiment' : 'boolean')

    const result =
        resultType === 'sentiment' ||
        isExplicitEvaluationNotApplicable(rawApplicable) ||
        rawResult === null ||
        rawResult === undefined
            ? null
            : isExplicitEvaluationPass(rawResult)

    return {
        evaluation_type: evaluationType,
        result_type: resultType,
        result,
        sentiment_label: sentimentLabel,
        sentiment_score: normalizeOptionalNumber(rawSentimentScore),
        applicable: normalizeEvaluationApplicable(rawApplicable),
    }
}

export function mapEvaluationRunRow(row: RawEvaluationRunRow): EvaluationRun {
    const normalizedResult = normalizeEvaluationResultProperties({
        rawResult: row[6],
        rawApplicable: row[8],
        rawEvaluationType: row[9],
        rawResultType: row[10],
        rawSentimentLabel: row[11],
        rawSentimentScore: row[12],
    })

    return {
        id: row[0],
        timestamp: row[1],
        evaluation_id: row[2],
        evaluation_name: row[3] || 'Unknown Evaluation',
        generation_id: row[4],
        trace_id: row[5],
        ...normalizedResult,
        reasoning: row[7] || 'No reasoning provided',
        status: 'completed' as const,
    }
}

export async function queryEvaluationRuns(params: {
    evaluationId?: string
    generationEventId?: string
    traceId?: string
    forceRefresh?: boolean
}): Promise<EvaluationRun[]> {
    const { evaluationId, generationEventId, traceId, forceRefresh } = params

    const propertyValue = evaluationId || generationEventId || traceId

    if (!propertyValue) {
        throw new Error('Either evaluationId, generationEventId, or traceId must be provided')
    }

    const propertyName = evaluationId ? '$ai_evaluation_id' : generationEventId ? '$ai_target_event_id' : '$ai_trace_id'

    const query = hogql`
        SELECT
            uuid,
            timestamp,
            properties.$ai_evaluation_id as evaluation_id,
            properties.$ai_evaluation_name as evaluation_name,
            properties.$ai_target_event_id as generation_id,
            properties.$ai_trace_id as trace_id,
            properties.$ai_evaluation_result as result,
            properties.$ai_evaluation_reasoning as reasoning,
            properties.$ai_evaluation_applicable as applicable,
            properties.$ai_evaluation_runtime as evaluation_type,
            properties.$ai_evaluation_result_type as result_type,
            properties.$ai_sentiment_label as sentiment_label,
            properties.$ai_sentiment_score as sentiment_score
        FROM events
        WHERE
            event = '$ai_evaluation'
            AND ${hogql.raw(`properties.${propertyName}`)} = ${propertyValue}
        ORDER BY timestamp DESC
        LIMIT ${EVALUATION_SUMMARY_MAX_RUNS}
    `

    const response = await api.queryHogQL(
        query,
        { scene: 'AIObservability', productKey: 'llm_analytics' },
        { ...(forceRefresh && { refresh: 'force_blocking' }) }
    )

    return (response.results || []).map(mapEvaluationRunRow)
}
