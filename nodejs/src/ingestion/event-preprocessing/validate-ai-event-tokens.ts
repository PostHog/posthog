import { IncomingEvent } from '../../types'
import { AI_EVENT_TYPES } from '../ai'
import { drop, ok } from '../pipelines/results'
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

export function createValidateAiEventTokensStep<T extends { event: IncomingEvent }>(): ProcessingStep<T, T> {
    return async function validateAiEventTokensStep(input) {
        const { event } = input

        if (!AI_EVENT_TYPES.has(event.event.event)) {
            return Promise.resolve(ok(input))
        }

        const properties = event.event.properties

        if (!properties) {
            return Promise.resolve(ok(input))
        }

        for (const prop of TOKEN_PROPERTIES) {
            const value = properties[prop]

            if (!isValidBigDecimalInput(value)) {
                return Promise.resolve(
                    drop(
                        `invalid_ai_token_property:${prop}`,
                        [],
                        [
                            {
                                type: 'invalid_ai_token_property',
                                details: {
                                    property: prop,
                                    value: String(value),
                                    valueType: typeof value,
                                },
                            },
                        ]
                    )
                )
            }
        }

        return Promise.resolve(ok(input))
    }
}
