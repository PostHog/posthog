import { EventSchemaEnforcement, IncomingEventWithTeam } from '../../types'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { isValidClickHouseDateTime } from './clickhouse-datetime-parser'

/**
 * Checks if a value can be coerced to the given PostHog property type.
 * This matches PostHog's query-time type coercion behavior.
 * See: posthog/hogql/transforms/property_types.py
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
            // Accepts: numbers, numeric strings, booleans
            if (typeof value === 'number') {
                return true
            }
            if (typeof value === 'boolean') {
                return true
            }
            if (typeof value === 'string') {
                const trimmed = value.trim()
                return trimmed !== '' && !isNaN(Number(trimmed))
            }
            return false

        case 'Boolean':
            // Accepts: booleans, "true"/"false" strings (case insensitive)
            if (typeof value === 'boolean') {
                return true
            }
            if (typeof value === 'string') {
                const lower = value.toLowerCase()
                return lower === 'true' || lower === 'false'
            }
            return false

        case 'DateTime':
            return isValidClickHouseDateTime(value)

        case 'Object':
            // Accepts: plain objects and arrays (null is already handled above).
            // Event properties come from JSON so we won't see Promises/Dates here.
            return typeof value === 'object'

        default:
            // Unknown type - allow by default
            return true
    }
}

/**
 * Checks if a value can be coerced to ANY of the given property types.
 * Used when a property has multiple types from different property groups.
 */
function canCoerceToAnyType(value: unknown, propertyTypes: string[]): boolean {
    if (propertyTypes.length === 0) {
        return true
    }
    return propertyTypes.some((type) => canCoerceToType(value, type))
}

export interface SchemaValidationError {
    propertyName: string
    reason: 'missing_required' | 'type_mismatch'
    expectedTypes?: string[]
    actualValue?: unknown
}

export interface SchemaValidationResult {
    valid: boolean
    errors: SchemaValidationError[]
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

    for (const property of schema.required_properties) {
        const value = eventProperties?.[property.name]

        // Check if required property is missing
        if (value === null || value === undefined) {
            errors.push({
                propertyName: property.name,
                reason: 'missing_required',
            })
            continue
        }

        // Check if value can be coerced to any of the expected types
        if (!canCoerceToAnyType(value, property.property_types)) {
            errors.push({
                propertyName: property.name,
                reason: 'type_mismatch',
                expectedTypes: property.property_types,
                actualValue: value,
            })
        }
    }

    return {
        valid: errors.length === 0,
        errors,
    }
}

/**
 * Finds the enforced schema for an event, if any.
 */
export function findEnforcedSchema(
    eventName: string,
    enforcedSchemas: EventSchemaEnforcement[]
): EventSchemaEnforcement | undefined {
    return enforcedSchemas.find((schema) => schema.event_name === eventName)
}

/**
 * Creates a processing step that validates events against enforced schemas.
 * Events that fail validation are dropped and an ingestion warning is emitted.
 *
 * @param schemaManager - Manager for fetching enforced schemas (uses caching internally)
 */
export function createValidateEventSchemaStep<T extends { eventWithTeam: IncomingEventWithTeam }>(
    schemaManager: EventSchemaEnforcementManager
): ProcessingStep<T, T> {
    return async function validateEventSchemaStep(input) {
        const { eventWithTeam } = input
        const { event, team } = eventWithTeam

        const enforcedSchemas = await schemaManager.getSchemas(team.id)
        if (enforcedSchemas.length === 0) {
            return ok(input)
        }

        const schema = findEnforcedSchema(event.event, enforcedSchemas)
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
                            })),
                        },
                    },
                ]
            )
        }

        return ok(input)
    }
}
