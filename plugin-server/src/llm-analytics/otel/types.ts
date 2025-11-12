/**
 * TypeScript types for OpenTelemetry trace ingestion.
 *
 * These types represent the subset of OTLP trace data we care about
 * for converting to PostHog AI events.
 */

/**
 * Simplified OTel Span representation.
 * Maps to opentelemetry.proto.trace.v1.Span
 */
export interface OTelSpan {
    trace_id: string // hex-encoded 16-byte trace ID
    span_id: string // hex-encoded 8-byte span ID
    parent_span_id?: string // hex-encoded 8-byte parent span ID
    name: string
    kind: SpanKind
    start_time_unix_nano: string // nanoseconds since epoch
    end_time_unix_nano: string // nanoseconds since epoch
    attributes: Record<string, AttributeValue>
    events: SpanEvent[]
    links: SpanLink[]
    status: SpanStatus
}

/**
 * Span kind enum
 */
export enum SpanKind {
    UNSPECIFIED = 0,
    INTERNAL = 1,
    SERVER = 2,
    CLIENT = 3,
    PRODUCER = 4,
    CONSUMER = 5,
}

/**
 * Attribute value types
 */
export type AttributeValue = string | number | boolean | string[] | number[]

/**
 * Span event
 */
export interface SpanEvent {
    time_unix_nano: string
    name: string
    attributes: Record<string, AttributeValue>
}

/**
 * Span link
 */
export interface SpanLink {
    trace_id: string
    span_id: string
    attributes: Record<string, AttributeValue>
}

/**
 * Span status
 */
export interface SpanStatus {
    code: SpanStatusCode
    message?: string
}

export enum SpanStatusCode {
    UNSET = 0,
    OK = 1,
    ERROR = 2,
}

/**
 * Resource represents the entity producing telemetry.
 */
export interface Resource {
    attributes: Record<string, AttributeValue>
}

/**
 * Instrumentation scope (library/tracer info)
 */
export interface InstrumentationScope {
    name: string
    version?: string
    attributes?: Record<string, AttributeValue>
}

/**
 * Baggage context propagation
 */
export interface Baggage {
    [key: string]: string
}

/**
 * Parsed OTLP trace request
 */
export interface ParsedOTLPRequest {
    spans: OTelSpan[]
    resource: Resource
    scope: InstrumentationScope
    baggage?: Baggage
}

/**
 * PostHog AI event properties (subset relevant for OTel mapping)
 */
export interface AIEventProperties {
    // Core identifiers
    $ai_trace_id: string
    $ai_span_id: string
    $ai_parent_id?: string
    $ai_session_id?: string
    $ai_generation_id?: string

    // Model info
    $ai_model?: string
    $ai_provider?: string

    // Token usage
    $ai_input_tokens?: number
    $ai_output_tokens?: number
    $ai_cache_read_tokens?: number
    $ai_cache_write_tokens?: number

    // Cost
    $ai_input_cost_usd?: number
    $ai_output_cost_usd?: number
    $ai_total_cost_usd?: number

    // Timing
    $ai_latency?: number // seconds

    // Error tracking
    $ai_is_error?: boolean
    $ai_error_message?: string

    // Model parameters
    $ai_temperature?: number
    $ai_max_tokens?: number
    $ai_stream?: boolean

    // Content (may be URLs to blob storage)
    $ai_input?: string
    $ai_output_choices?: string

    // Metadata
    $ai_otel_transformer_version: string
    $ai_otel_span_kind?: string
    $ai_otel_status_code?: string

    // Additional properties
    [key: string]: AttributeValue | undefined
}

/**
 * PostHog AI event
 */
export interface AIEvent {
    event: AIEventType
    distinct_id: string
    timestamp: string // ISO 8601
    properties: AIEventProperties
}

/**
 * AI event types
 */
export type AIEventType = '$ai_generation' | '$ai_embedding' | '$ai_span' | '$ai_trace' | '$ai_metric' | '$ai_feedback'

/**
 * Transformer version
 */
export const OTEL_TRANSFORMER_VERSION = '1.0.0'

/**
 * Extracted attributes from conventions
 */
export interface ExtractedAttributes {
    // Core
    model?: string
    provider?: string
    trace_id?: string
    span_id?: string
    parent_id?: string
    session_id?: string

    // Tokens
    input_tokens?: number
    output_tokens?: number
    cache_read_tokens?: number
    cache_write_tokens?: number

    // Cost
    input_cost_usd?: number
    output_cost_usd?: number
    request_cost_usd?: number
    total_cost_usd?: number

    // Operation
    operation_name?: string // chat, completion, embedding

    // Content
    input?: string
    output?: string
    prompt?: string | object
    completion?: string | object

    // Parameters
    temperature?: number
    max_tokens?: number
    stream?: boolean

    // Error
    is_error?: boolean
    error_message?: string
}
