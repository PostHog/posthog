/**
 * PostHog-native OpenTelemetry attribute conventions.
 *
 * These attributes have the highest priority and follow the pattern:
 * posthog.ai.*
 *
 * Example usage in OTel SDK:
 * ```python
 * span.set_attribute("posthog.ai.model", "gpt-4")
 * span.set_attribute("posthog.ai.provider", "openai")
 * span.set_attribute("posthog.ai.session_id", "sess_123")
 * ```
 */
import type { AttributeValue, ExtractedAttributes, OTelSpan } from '../types'

/**
 * PostHog-native attribute namespace
 */
const POSTHOG_PREFIX = 'posthog.ai.'

/**
 * Get attribute with PostHog prefix
 */
function getPostHogAttr(span: OTelSpan, key: string): AttributeValue | undefined {
    return span.attributes[`${POSTHOG_PREFIX}${key}`]
}

/**
 * Get string attribute
 */
function getString(span: OTelSpan, key: string): string | undefined {
    const value = getPostHogAttr(span, key)
    return typeof value === 'string' ? value : undefined
}

/**
 * Get number attribute
 */
function getNumber(span: OTelSpan, key: string): number | undefined {
    const value = getPostHogAttr(span, key)
    return typeof value === 'number' ? value : undefined
}

/**
 * Get boolean attribute
 */
function getBoolean(span: OTelSpan, key: string): boolean | undefined {
    const value = getPostHogAttr(span, key)
    return typeof value === 'boolean' ? value : undefined
}

/**
 * Extract PostHog-native attributes from span.
 * Returns undefined for missing attributes (not null).
 */
export function extractPostHogNativeAttributes(span: OTelSpan): ExtractedAttributes {
    return {
        // Core identifiers
        model: getString(span, 'model'),
        provider: getString(span, 'provider'),
        trace_id: getString(span, 'trace_id'),
        span_id: getString(span, 'span_id'),
        parent_id: getString(span, 'parent_id'),
        session_id: getString(span, 'session_id'),

        // Token usage
        input_tokens: getNumber(span, 'input_tokens'),
        output_tokens: getNumber(span, 'output_tokens'),
        cache_read_tokens: getNumber(span, 'cache_read_tokens'),
        cache_write_tokens: getNumber(span, 'cache_write_tokens'),

        // Cost
        input_cost_usd: getNumber(span, 'input_cost_usd'),
        output_cost_usd: getNumber(span, 'output_cost_usd'),
        request_cost_usd: getNumber(span, 'request_cost_usd'),
        total_cost_usd: getNumber(span, 'total_cost_usd'),

        // Operation
        operation_name: getString(span, 'operation_name'),

        // Content
        input: getString(span, 'input'),
        output: getString(span, 'output'),
        prompt: getPostHogAttr(span, 'prompt'),
        completion: getPostHogAttr(span, 'completion'),

        // Model parameters
        temperature: getNumber(span, 'temperature'),
        max_tokens: getNumber(span, 'max_tokens'),
        stream: getBoolean(span, 'stream'),

        // Error tracking
        is_error: getBoolean(span, 'is_error'),
        error_message: getString(span, 'error_message'),
    }
}

/**
 * Check if span has any PostHog-native attributes
 */
export function hasPostHogAttributes(span: OTelSpan): boolean {
    return Object.keys(span.attributes).some((key) => key.startsWith(POSTHOG_PREFIX))
}

/**
 * List of supported PostHog-native attributes for documentation
 */
export const SUPPORTED_POSTHOG_ATTRIBUTES = [
    // Core
    'posthog.ai.model',
    'posthog.ai.provider',
    'posthog.ai.trace_id',
    'posthog.ai.span_id',
    'posthog.ai.parent_id',
    'posthog.ai.session_id',
    'posthog.ai.generation_id',

    // Tokens
    'posthog.ai.input_tokens',
    'posthog.ai.output_tokens',
    'posthog.ai.cache_read_tokens',
    'posthog.ai.cache_write_tokens',

    // Cost
    'posthog.ai.input_cost_usd',
    'posthog.ai.output_cost_usd',
    'posthog.ai.request_cost_usd',
    'posthog.ai.total_cost_usd',

    // Operation
    'posthog.ai.operation_name',

    // Content
    'posthog.ai.input',
    'posthog.ai.output',
    'posthog.ai.prompt',
    'posthog.ai.completion',

    // Parameters
    'posthog.ai.temperature',
    'posthog.ai.max_tokens',
    'posthog.ai.stream',

    // Error
    'posthog.ai.is_error',
    'posthog.ai.error_message',
] as const
