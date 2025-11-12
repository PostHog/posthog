/**
 * OpenTelemetry ingestion validation constants and limits.
 *
 * These limits align with:
 * - OpenTelemetry SDK defaults
 * - Industry standard observability platforms (Jaeger, New Relic, Datadog)
 * - PostHog infrastructure constraints
 */

export const OTEL_LIMITS = {
    /**
     * Maximum number of spans per OTLP export request.
     * Most OTel SDKs batch export around 512 spans by default.
     */
    MAX_SPANS_PER_REQUEST: 1000,

    /**
     * Maximum number of attributes per span.
     * Aligns with OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT default.
     */
    MAX_ATTRIBUTES_PER_SPAN: 128,

    /**
     * Maximum number of events per span.
     * Aligns with OTEL_SPAN_EVENT_COUNT_LIMIT default.
     */
    MAX_EVENTS_PER_SPAN: 128,

    /**
     * Maximum number of links per span.
     * Aligns with OTEL_SPAN_LINK_COUNT_LIMIT default.
     */
    MAX_LINKS_PER_SPAN: 128,

    /**
     * Maximum length of an attribute value in bytes.
     * Set generously to 100KB to accommodate LLM prompts/completions.
     * Can be extended to blob storage in future if needed.
     */
    MAX_ATTRIBUTE_VALUE_LENGTH: 100_000,

    /**
     * Maximum length of span name.
     * Aligns with OTel recommendations.
     */
    MAX_SPAN_NAME_LENGTH: 1024,

    /**
     * Maximum length of resource attributes.
     */
    MAX_RESOURCE_ATTRIBUTES: 64,
} as const

export interface ValidationError {
    field: string
    value: number
    limit: number
    message: string
}

export interface ValidationResult {
    valid: boolean
    errors: ValidationError[]
}

/**
 * Validate attribute value length.
 */
export function validateAttributeValue(key: string, value: unknown): ValidationError | null {
    if (typeof value === 'string' && value.length > OTEL_LIMITS.MAX_ATTRIBUTE_VALUE_LENGTH) {
        return {
            field: `attribute.${key}`,
            value: value.length,
            limit: OTEL_LIMITS.MAX_ATTRIBUTE_VALUE_LENGTH,
            message: `Attribute '${key}' exceeds ${OTEL_LIMITS.MAX_ATTRIBUTE_VALUE_LENGTH} bytes (${value.length} bytes). Consider reducing payload size.`,
        }
    }
    return null
}

/**
 * Validate span name length.
 */
export function validateSpanName(name: string): ValidationError | null {
    if (name.length > OTEL_LIMITS.MAX_SPAN_NAME_LENGTH) {
        return {
            field: 'span.name',
            value: name.length,
            limit: OTEL_LIMITS.MAX_SPAN_NAME_LENGTH,
            message: `Span name exceeds ${OTEL_LIMITS.MAX_SPAN_NAME_LENGTH} characters (${name.length} characters).`,
        }
    }
    return null
}

/**
 * Validate number of attributes in span.
 */
export function validateAttributeCount(attributeCount: number): ValidationError | null {
    if (attributeCount > OTEL_LIMITS.MAX_ATTRIBUTES_PER_SPAN) {
        return {
            field: 'span.attributes',
            value: attributeCount,
            limit: OTEL_LIMITS.MAX_ATTRIBUTES_PER_SPAN,
            message: `Span has ${attributeCount} attributes, maximum is ${OTEL_LIMITS.MAX_ATTRIBUTES_PER_SPAN}.`,
        }
    }
    return null
}

/**
 * Validate number of events in span.
 */
export function validateEventCount(eventCount: number): ValidationError | null {
    if (eventCount > OTEL_LIMITS.MAX_EVENTS_PER_SPAN) {
        return {
            field: 'span.events',
            value: eventCount,
            limit: OTEL_LIMITS.MAX_EVENTS_PER_SPAN,
            message: `Span has ${eventCount} events, maximum is ${OTEL_LIMITS.MAX_EVENTS_PER_SPAN}.`,
        }
    }
    return null
}

/**
 * Validate number of links in span.
 */
export function validateLinkCount(linkCount: number): ValidationError | null {
    if (linkCount > OTEL_LIMITS.MAX_LINKS_PER_SPAN) {
        return {
            field: 'span.links',
            value: linkCount,
            limit: OTEL_LIMITS.MAX_LINKS_PER_SPAN,
            message: `Span has ${linkCount} links, maximum is ${OTEL_LIMITS.MAX_LINKS_PER_SPAN}.`,
        }
    }
    return null
}

/**
 * Validate total span count in request.
 */
export function validateSpanCount(spanCount: number): ValidationError | null {
    if (spanCount > OTEL_LIMITS.MAX_SPANS_PER_REQUEST) {
        return {
            field: 'request.spans',
            value: spanCount,
            limit: OTEL_LIMITS.MAX_SPANS_PER_REQUEST,
            message: `Request contains ${spanCount} spans, maximum is ${OTEL_LIMITS.MAX_SPANS_PER_REQUEST}. Configure batch size in your OTel SDK (e.g., OTEL_BSP_MAX_EXPORT_BATCH_SIZE).`,
        }
    }
    return null
}
