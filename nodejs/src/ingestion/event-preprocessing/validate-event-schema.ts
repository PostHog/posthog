import { EventSchemaEnforcement, PipelineEvent, PropertyValidationRules, Team } from '../../types'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { isValidClickHouseDateTime } from './clickhouse-datetime-parser'

/**
 * Checks if a value can be coerced to the given PostHog property type.
 * See: PropertySwapper._field_type_to_property_call in posthog/hogql/transforms/property_types.py
 */
function canCoerceToType(value: unknown, propertyType: string): boolean {
    if (value === null || value === undefined) {
        return false
    }

    switch (propertyType) {
        case 'String':
            // Everything can be coerced to string
            return true

        case 'Numeric':
            // Accepts: numbers, numeric strings
            // Rejects: Infinity, -Infinity, NaN, booleans (these become null in ClickHouse)
            if (typeof value === 'number') {
                return Number.isFinite(value)
            }
            if (typeof value === 'string') {
                const trimmed = value.trim()
                const num = Number(trimmed)
                return trimmed !== '' && Number.isFinite(num)
            }
            return false

        case 'Boolean':
            // Accepts: booleans, "true"/"false" strings (case sensitive - ClickHouse transform only matches lowercase)
            if (typeof value === 'boolean') {
                return true
            }
            if (typeof value === 'string') {
                return value === 'true' || value === 'false'
            }
            return false

        case 'DateTime':
            return isValidClickHouseDateTime(value)

        case 'Object':
            return typeof value === 'object'

        default:
            // Unknown type - allow by default
            return true
    }
}

export interface SchemaValidationError {
    propertyName: string
    reason: 'missing_required' | 'type_mismatch' | 'value_validation_failed'
    expectedTypes?: string[]
    actualValue?: unknown
    validationDetail?: string
}

export interface SchemaValidationResult {
    valid: boolean
    errors: SchemaValidationError[]
}

function checkStringEnum(value: unknown, allowedValues: string[]): boolean {
    return allowedValues.includes(String(value))
}

function checkStringNotEnum(value: unknown, deniedValues: string[]): boolean {
    return !deniedValues.includes(String(value))
}

function checkNumericRange(value: unknown, rules: PropertyValidationRules): boolean {
    let numValue: number
    if (typeof value === 'number') {
        numValue = value
    } else if (typeof value === 'string') {
        numValue = Number(value.trim())
    } else {
        return false
    }
    if (!Number.isFinite(numValue)) {
        return false
    }

    if (rules.minimum !== undefined && numValue < rules.minimum) {
        return false
    }
    if (rules.exclusiveMinimum !== undefined && numValue <= rules.exclusiveMinimum) {
        return false
    }
    if (rules.maximum !== undefined && numValue > rules.maximum) {
        return false
    }
    if (rules.exclusiveMaximum !== undefined && numValue >= rules.exclusiveMaximum) {
        return false
    }
    return true
}

/**
 * Validates a property value against validation rules from multiple property groups.
 * Uses OR semantics: the value passes if it satisfies ANY of the rule sets.
 */
function validatePropertyValue(value: unknown, ruleSets: PropertyValidationRules[]): string | null {
    for (const rules of ruleSets) {
        if (rules.enum) {
            if (checkStringEnum(value, rules.enum)) {
                return null
            }
        } else if (rules.not?.enum) {
            if (checkStringNotEnum(value, rules.not.enum)) {
                return null
            }
        } else if (
            rules.minimum !== undefined ||
            rules.exclusiveMinimum !== undefined ||
            rules.maximum !== undefined ||
            rules.exclusiveMaximum !== undefined
        ) {
            if (checkNumericRange(value, rules)) {
                return null
            }
        } else {
            return null
        }
    }

    // Build a detail message from the first rule set
    const firstRules = ruleSets[0]
    if (firstRules.enum) {
        return `value must be one of: ${firstRules.enum.join(', ')}`
    } else if (firstRules.not?.enum) {
        return `value must not be one of: ${firstRules.not.enum.join(', ')}`
    } else {
        const bounds: string[] = []
        if (firstRules.minimum !== undefined) {
            bounds.push(`>= ${firstRules.minimum}`)
        }
        if (firstRules.exclusiveMinimum !== undefined) {
            bounds.push(`> ${firstRules.exclusiveMinimum}`)
        }
        if (firstRules.maximum !== undefined) {
            bounds.push(`<= ${firstRules.maximum}`)
        }
        if (firstRules.exclusiveMaximum !== undefined) {
            bounds.push(`< ${firstRules.exclusiveMaximum}`)
        }
        return `value must be ${bounds.join(' and ')}`
    }
}

/**
 * Validates an event's properties against an enforced schema.
 * Only required properties are validated - optional properties are not included in the schema.
 */
export function validateEventAgainstSchema(
    eventProperties: Record<string, unknown> | undefined,
    schema: EventSchemaEnforcement
): SchemaValidationResult {
    const errors: SchemaValidationError[] = []

    for (const [propertyName, propertyTypes] of schema.required_properties) {
        const value = eventProperties?.[propertyName]

        if (value === null || value === undefined) {
            errors.push({
                propertyName,
                reason: 'missing_required',
            })
            continue
        }

        if (!propertyTypes.some((type) => canCoerceToType(value, type))) {
            errors.push({
                propertyName,
                reason: 'type_mismatch',
                expectedTypes: propertyTypes,
                actualValue: value,
            })
            continue
        }

        const validationRuleSets = schema.property_validation_rules.get(propertyName)
        if (validationRuleSets && validationRuleSets.length > 0) {
            const detail = validatePropertyValue(value, validationRuleSets)
            if (detail !== null) {
                errors.push({
                    propertyName,
                    reason: 'value_validation_failed',
                    actualValue: value,
                    validationDetail: detail,
                })
            }
        }
    }

    return {
        valid: errors.length === 0,
        errors,
    }
}

/**
 * Creates a processing step that validates events against enforced schemas.
 * Events that fail validation are dropped and an ingestion warning is emitted.
 *
 * @param schemaManager - Manager for fetching enforced schemas (uses caching internally)
 */
export function createValidateEventSchemaStep<T extends { event: PipelineEvent; team: Team }>(
    schemaManager: EventSchemaEnforcementManager
): ProcessingStep<T, T> {
    return async function validateEventSchemaStep(input) {
        const { event, team } = input

        const enforcedSchemas = await schemaManager.getSchemas(team.id)
        if (enforcedSchemas.size === 0) {
            return ok(input)
        }

        const schema = enforcedSchemas.get(event.event)
        if (!schema) {
            return ok(input)
        }

        const validationResult = validateEventAgainstSchema(event.properties, schema)

        if (!validationResult.valid) {
            return drop(
                'schema_validation_failed',
                [],
                [
                    {
                        type: 'schema_validation_failed',
                        details: {
                            eventUuid: event.uuid,
                            eventName: event.event,
                            distinctId: event.distinct_id,
                            errors: validationResult.errors.map((err) => ({
                                property: err.propertyName,
                                reason: err.reason,
                                expectedTypes: err.expectedTypes,
                                actualValue:
                                    err.actualValue !== undefined
                                        ? typeof err.actualValue === 'object'
                                            ? JSON.stringify(err.actualValue)
                                            : String(err.actualValue)
                                        : undefined,
                                validationDetail: err.validationDetail,
                            })),
                        },
                    },
                ]
            )
        }

        return ok(input)
    }
}
