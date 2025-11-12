/**
 * Core OTel span to PostHog AI event transformer.
 *
 * Transforms OpenTelemetry spans into PostHog AI events using a waterfall
 * pattern for attribute extraction:
 * 1. PostHog native attributes (highest priority)
 * 2. GenAI semantic conventions (fallback)
 * 3. OTel span built-ins (trace_id, span_id, etc.)
 */
import { extractGenAIAttributes, hasGenAIAttributes } from './conventions/genai'
import { extractPostHogNativeAttributes, hasPostHogAttributes } from './conventions/posthog-native'
import type {
    AIEvent,
    AIEventProperties,
    AIEventType,
    Baggage,
    ExtractedAttributes,
    InstrumentationScope,
    OTEL_TRANSFORMER_VERSION,
    OTelSpan,
    Resource,
    SpanStatusCode,
} from './types'
import {
    type ValidationError,
    validateAttributeCount,
    validateAttributeValue,
    validateEventCount,
    validateLinkCount,
    validateSpanName,
} from './validation'

export { OTEL_TRANSFORMER_VERSION } from './types'

/**
 * Transform a single OTel span to PostHog AI event.
 */
export function transformSpanToAIEvent(
    span: OTelSpan,
    resource: Resource,
    scope: InstrumentationScope,
    baggage?: Baggage
): { event: AIEvent; errors: ValidationError[] } {
    const errors: ValidationError[] = []

    // Validate span
    const validation = validateSpan(span)
    errors.push(...validation)

    // Extract attributes using waterfall pattern
    const posthogAttrs = extractPostHogNativeAttributes(span)
    const genaiAttrs = extractGenAIAttributes(span)

    // Merge with precedence: PostHog > GenAI
    const mergedAttrs: ExtractedAttributes = {
        ...genaiAttrs,
        ...posthogAttrs, // PostHog overrides GenAI
    }

    // Build AI event properties
    const properties = buildEventProperties(span, mergedAttrs, resource, scope, baggage)

    // Determine event type
    const eventType = determineEventType(span, mergedAttrs)

    // Calculate timestamp and latency
    const timestamp = calculateTimestamp(span)

    // Get distinct_id (from resource attributes or default)
    const distinct_id = extractDistinctId(resource, baggage)

    const event: AIEvent = {
        event: eventType,
        distinct_id,
        timestamp,
        properties,
    }

    return { event, errors }
}

/**
 * Validate span against limits
 */
function validateSpan(span: OTelSpan): ValidationError[] {
    const errors: ValidationError[] = []

    // Validate span name
    const nameError = validateSpanName(span.name)
    if (nameError) errors.push(nameError)

    // Validate attribute count
    const attrCountError = validateAttributeCount(Object.keys(span.attributes).length)
    if (attrCountError) errors.push(attrCountError)

    // Validate event count
    const eventCountError = validateEventCount(span.events?.length || 0)
    if (eventCountError) errors.push(eventCountError)

    // Validate link count
    const linkCountError = validateLinkCount(span.links?.length || 0)
    if (linkCountError) errors.push(linkCountError)

    // Validate attribute values
    for (const [key, value] of Object.entries(span.attributes)) {
        const valueError = validateAttributeValue(key, value)
        if (valueError) errors.push(valueError)
    }

    return errors
}

/**
 * Build PostHog AI event properties from extracted attributes
 */
function buildEventProperties(
    span: OTelSpan,
    attrs: ExtractedAttributes,
    resource: Resource,
    scope: InstrumentationScope,
    baggage?: Baggage
): AIEventProperties {
    // Core identifiers (prefer extracted, fallback to span built-ins)
    const trace_id = attrs.trace_id || span.trace_id
    const span_id = attrs.span_id || span.span_id
    const parent_id = attrs.parent_id || span.parent_span_id

    // Session ID (prefer extracted, fallback to baggage)
    const session_id = attrs.session_id || baggage?.session_id || baggage?.['posthog.session_id']

    // Calculate latency
    const latency = calculateLatency(span)

    // Detect error from span status
    const is_error = attrs.is_error !== undefined ? attrs.is_error : span.status.code === SpanStatusCode.ERROR
    const error_message = attrs.error_message || (is_error ? span.status.message : undefined)

    // Build base properties
    const properties: AIEventProperties = {
        // Core IDs
        $ai_trace_id: trace_id,
        $ai_span_id: span_id,
        ...(parent_id && { $ai_parent_id: parent_id }),
        ...(session_id && { $ai_session_id: session_id }),

        // Model info
        ...(attrs.model && { $ai_model: attrs.model }),
        ...(attrs.provider && { $ai_provider: attrs.provider }),

        // Tokens
        ...(attrs.input_tokens !== undefined && { $ai_input_tokens: attrs.input_tokens }),
        ...(attrs.output_tokens !== undefined && { $ai_output_tokens: attrs.output_tokens }),
        ...(attrs.cache_read_tokens !== undefined && { $ai_cache_read_tokens: attrs.cache_read_tokens }),
        ...(attrs.cache_write_tokens !== undefined && { $ai_cache_write_tokens: attrs.cache_write_tokens }),

        // Cost
        ...(attrs.input_cost_usd !== undefined && { $ai_input_cost_usd: attrs.input_cost_usd }),
        ...(attrs.output_cost_usd !== undefined && { $ai_output_cost_usd: attrs.output_cost_usd }),
        ...(attrs.total_cost_usd !== undefined && { $ai_total_cost_usd: attrs.total_cost_usd }),

        // Timing
        ...(latency !== undefined && { $ai_latency: latency }),

        // Error
        ...(is_error && { $ai_is_error: is_error }),
        ...(error_message && { $ai_error_message: error_message }),

        // Model parameters
        ...(attrs.temperature !== undefined && { $ai_temperature: attrs.temperature }),
        ...(attrs.max_tokens !== undefined && { $ai_max_tokens: attrs.max_tokens }),
        ...(attrs.stream !== undefined && { $ai_stream: attrs.stream }),

        // Content (if present and not too large)
        ...(attrs.input && { $ai_input: stringifyContent(attrs.input) }),
        ...(attrs.output && { $ai_output_choices: stringifyContent(attrs.output) }),
        ...(attrs.prompt && { $ai_input: stringifyContent(attrs.prompt) }),
        ...(attrs.completion && { $ai_output_choices: stringifyContent(attrs.completion) }),

        // Metadata
        $ai_otel_transformer_version: '1.0.0',
        $ai_otel_span_kind: span.kind.toString(),
        $ai_otel_status_code: span.status.code.toString(),

        // Resource attributes (service name, etc.)
        ...(resource.attributes['service.name'] && {
            $ai_service_name: resource.attributes['service.name'] as string,
        }),

        // Instrumentation scope
        $ai_instrumentation_scope_name: scope.name,
        ...(scope.version && { $ai_instrumentation_scope_version: scope.version }),
    }

    // Add remaining span attributes (not already mapped)
    const mappedKeys = new Set([
        'posthog.ai.model',
        'posthog.ai.provider',
        'gen_ai.system',
        'gen_ai.request.model',
        'gen_ai.response.model',
        'gen_ai.operation.name',
        'gen_ai.usage.input_tokens',
        'gen_ai.usage.output_tokens',
        'gen_ai.prompt',
        'gen_ai.completion',
        'service.name',
    ])

    for (const [key, value] of Object.entries(span.attributes)) {
        if (!mappedKeys.has(key) && !key.startsWith('posthog.ai.') && !key.startsWith('gen_ai.')) {
            // Add unmapped attributes with prefix
            properties[`otel.${key}`] = value
        }
    }

    return properties
}

/**
 * Determine AI event type from span
 */
function determineEventType(span: OTelSpan, attrs: ExtractedAttributes): AIEventType {
    const opName = attrs.operation_name?.toLowerCase()

    // Check operation name
    if (opName === 'chat' || opName === 'completion') {
        return '$ai_generation'
    } else if (opName === 'embedding' || opName === 'embeddings') {
        return '$ai_embedding'
    }

    // Check if span is root (no parent)
    if (!span.parent_span_id) {
        return '$ai_trace'
    }

    // Default to generic span
    return '$ai_span'
}

/**
 * Calculate timestamp from span start time
 */
function calculateTimestamp(span: OTelSpan): string {
    const nanos = BigInt(span.start_time_unix_nano)
    const millis = Number(nanos / BigInt(1_000_000))
    return new Date(millis).toISOString()
}

/**
 * Calculate latency in seconds from span start/end time
 */
function calculateLatency(span: OTelSpan): number | undefined {
    if (!span.end_time_unix_nano) return undefined

    const startNanos = BigInt(span.start_time_unix_nano)
    const endNanos = BigInt(span.end_time_unix_nano)
    const durationNanos = endNanos - startNanos

    // Convert to seconds
    return Number(durationNanos) / 1_000_000_000
}

/**
 * Extract distinct_id from resource or baggage
 */
function extractDistinctId(resource: Resource, baggage?: Baggage): string {
    // Try resource attributes
    const userId =
        resource.attributes['user.id'] ||
        resource.attributes['enduser.id'] ||
        resource.attributes['posthog.distinct_id']

    if (typeof userId === 'string') {
        return userId
    }

    // Try baggage
    if (baggage?.user_id) {
        return baggage.user_id
    }
    if (baggage?.distinct_id) {
        return baggage.distinct_id
    }

    // Default to anonymous
    return 'anonymous'
}

/**
 * Stringify content (handles objects and strings)
 */
function stringifyContent(content: any): string {
    if (typeof content === 'string') {
        return content
    }
    return JSON.stringify(content)
}

/**
 * Check if span uses PostHog or GenAI conventions
 */
export function spanUsesKnownConventions(span: OTelSpan): boolean {
    return hasPostHogAttributes(span) || hasGenAIAttributes(span)
}
