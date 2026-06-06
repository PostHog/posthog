import { PipelineEvent } from '../../types'
import { AI_EVENT_TYPES } from '../ai'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

const TOKEN_PROPERTIES = [
    '$ai_input_tokens',
    '$ai_output_tokens',
    '$ai_reasoning_tokens',
    '$ai_cache_read_input_tokens',
    '$ai_cache_creation_input_tokens',
] as const

/**
 * Validates that a value can be safely used with js-big-decimal for cost calculations.
 * Valid values are:
 * - Finite numbers (not NaN, not Infinity)
 * - Numeric strings (e.g., '100', '100.5', '-100')
 * - null/undefined (will be defaulted to 0 downstream)
 */
function isValidBigDecimalInput(value: unknown): boolean {
    if (value === null || value === undefined) {
        return true
    }

    if (typeof value === 'number') {
        return Number.isFinite(value)
    }

    if (typeof value === 'string') {
        if (value === '') {
            return true
        }
        const parsed = Number(value)
        return !Number.isNaN(parsed) && Number.isFinite(parsed)
    }

    return false
}

/**
 * Some SDKs (e.g. posthog-ai < 7.3.0 with Vercel AI SDK V3) send token counts
 * as nested objects like `{ total: 10585, noCache: 10585, cacheRead: 0 }` instead
 * of plain numbers. Extract the numeric `total` field when present.
 */
function normalizeTokenValue(value: unknown): unknown {
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
        const obj = value as Record<string, unknown>
        if ('total' in obj) {
            return obj.total
        }
    }
    return value
}

export function createValidateAiEventTokensStep<T extends { event: PipelineEvent }>(): ProcessingStep<T, T> {
    return async function validateAiEventTokensStep(input) {
        const { event } = input

        if (!AI_EVENT_TYPES.has(event.event)) {
            return Promise.resolve(ok(input))
        }

        const properties = event.properties

        if (!properties) {
            return Promise.resolve(ok(input))
        }

        const warnings: PipelineWarning[] = []

        for (const prop of TOKEN_PROPERTIES) {
            if (!(prop in properties)) {
                continue
            }
            const raw = properties[prop]
            const normalized = normalizeTokenValue(raw)
            properties[prop] = normalized

            if (!isValidBigDecimalInput(normalized)) {
                warnings.push({
                    type: 'invalid_ai_token_property',
                    details: {
                        property: prop,
                        value: String(normalized),
                        valueType: typeof normalized,
                    },
                })
                properties[prop] = null
            }
        }

        return Promise.resolve(ok(input, [], warnings))
    }
}
