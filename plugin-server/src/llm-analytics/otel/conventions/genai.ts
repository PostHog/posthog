/**
 * OpenTelemetry GenAI semantic conventions.
 *
 * Based on: https://opentelemetry.io/docs/specs/semconv/gen-ai/
 *
 * These are standard attributes defined by the OpenTelemetry community
 * for generative AI workloads.
 *
 * Example usage in OTel SDK:
 * ```python
 * from opentelemetry.semconv.ai import SpanAttributes
 *
 * span.set_attribute(SpanAttributes.GEN_AI_SYSTEM, "openai")
 * span.set_attribute(SpanAttributes.GEN_AI_REQUEST_MODEL, "gpt-4")
 * span.set_attribute(SpanAttributes.GEN_AI_OPERATION_NAME, "chat")
 * ```
 */
import type { AttributeValue, ExtractedAttributes, OTelSpan } from '../types'

/**
 * Get attribute value
 */
function getAttr(span: OTelSpan, key: string): AttributeValue | undefined {
    return span.attributes[key]
}

/**
 * Get string attribute
 */
function getString(span: OTelSpan, key: string): string | undefined {
    const value = getAttr(span, key)
    return typeof value === 'string' ? value : undefined
}

/**
 * Get number attribute
 */
function getNumber(span: OTelSpan, key: string): number | undefined {
    const value = getAttr(span, key)
    return typeof value === 'number' ? value : undefined
}

/**
 * Parse JSON attribute if it's a string
 */
function parseJSON(value: AttributeValue | undefined): any {
    if (typeof value === 'string') {
        try {
            return JSON.parse(value)
        } catch {
            return value
        }
    }
    return value
}

/**
 * Extract model name from either request or response
 */
function extractModel(span: OTelSpan): string | undefined {
    return getString(span, 'gen_ai.request.model') || getString(span, 'gen_ai.response.model')
}

/**
 * Extract provider/system
 */
function extractProvider(span: OTelSpan): string | undefined {
    return getString(span, 'gen_ai.system')
}

/**
 * Extract token usage
 */
function extractTokenUsage(span: OTelSpan): {
    input_tokens?: number
    output_tokens?: number
    cache_read_tokens?: number
    cache_write_tokens?: number
} {
    return {
        input_tokens: getNumber(span, 'gen_ai.usage.input_tokens'),
        output_tokens: getNumber(span, 'gen_ai.usage.output_tokens'),
        // Cache tokens might not be standardized yet, but support if present
        cache_read_tokens: getNumber(span, 'gen_ai.usage.cache_read_input_tokens'),
        cache_write_tokens: getNumber(span, 'gen_ai.usage.cache_creation_input_tokens'),
    }
}

/**
 * Extract cost
 */
function extractCost(span: OTelSpan): {
    input_cost_usd?: number
    output_cost_usd?: number
    total_cost_usd?: number
} {
    const totalCost = getNumber(span, 'gen_ai.usage.cost')

    return {
        input_cost_usd: getNumber(span, 'gen_ai.usage.input_cost'),
        output_cost_usd: getNumber(span, 'gen_ai.usage.output_cost'),
        total_cost_usd: totalCost,
    }
}

/**
 * Extract model parameters
 */
function extractModelParams(span: OTelSpan): {
    temperature?: number
    max_tokens?: number
} {
    return {
        temperature: getNumber(span, 'gen_ai.request.temperature'),
        max_tokens:
            getNumber(span, 'gen_ai.request.max_tokens') || getNumber(span, 'gen_ai.request.max_completion_tokens'),
    }
}

/**
 * Extract content (prompt/completion)
 * GenAI conventions support multiple formats:
 * 1. JSON string: gen_ai.prompt = '[{"role": "user", "content": "..."}]'
 * 2. Flattened: gen_ai.prompt.0.role, gen_ai.prompt.0.content
 * 3. Simple string: gen_ai.prompt = "text"
 */
function extractContent(span: OTelSpan): {
    prompt?: string | object
    completion?: string | object
    input?: string
    output?: string
} {
    const prompt = getAttr(span, 'gen_ai.prompt')
    const completion = getAttr(span, 'gen_ai.completion')

    return {
        prompt: parseJSON(prompt),
        completion: parseJSON(completion),
        // Some implementations use these simpler names
        input: getString(span, 'gen_ai.input'),
        output: getString(span, 'gen_ai.output'),
    }
}

/**
 * Extract GenAI semantic convention attributes from span.
 * Returns undefined for missing attributes.
 */
export function extractGenAIAttributes(span: OTelSpan): ExtractedAttributes {
    const tokens = extractTokenUsage(span)
    const cost = extractCost(span)
    const params = extractModelParams(span)
    const content = extractContent(span)

    return {
        // Core
        model: extractModel(span),
        provider: extractProvider(span),
        operation_name: getString(span, 'gen_ai.operation.name'),

        // Tokens
        ...tokens,

        // Cost
        ...cost,

        // Parameters
        ...params,

        // Content
        ...content,
    }
}

/**
 * Check if span has any GenAI semantic convention attributes
 */
export function hasGenAIAttributes(span: OTelSpan): boolean {
    return Object.keys(span.attributes).some((key) => key.startsWith('gen_ai.'))
}

/**
 * List of supported GenAI semantic convention attributes
 */
export const SUPPORTED_GENAI_ATTRIBUTES = [
    // Core
    'gen_ai.system',
    'gen_ai.request.model',
    'gen_ai.response.model',
    'gen_ai.operation.name',

    // Usage
    'gen_ai.usage.input_tokens',
    'gen_ai.usage.output_tokens',
    'gen_ai.usage.cache_read_input_tokens',
    'gen_ai.usage.cache_creation_input_tokens',

    // Cost
    'gen_ai.usage.cost',
    'gen_ai.usage.input_cost',
    'gen_ai.usage.output_cost',

    // Request params
    'gen_ai.request.temperature',
    'gen_ai.request.max_tokens',
    'gen_ai.request.max_completion_tokens',
    'gen_ai.request.top_p',
    'gen_ai.request.top_k',
    'gen_ai.request.frequency_penalty',
    'gen_ai.request.presence_penalty',
    'gen_ai.request.stop_sequences',

    // Content
    'gen_ai.prompt',
    'gen_ai.completion',
    'gen_ai.input',
    'gen_ai.output',

    // Response
    'gen_ai.response.id',
    'gen_ai.response.finish_reasons',
] as const
