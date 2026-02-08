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
            // Accepts: plain objects and arrays (null is already handled above).
            // Event properties come from JSON so we won't see Promises/Dates here.
            return typeof value === 'object'

        default:
            // Unknown type - allow by default
            return true
    }
}

export interface SchemaValidationError {
    propertyName: string
    reason: 'missing_required' | 'type_mismatch'
    expectedType?: string
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

    for (const [propertyName, propertyType] of schema.required_properties) {
        const value = eventProperties?.[propertyName]

        if (value === null || value === undefined) {
            errors.push({
                propertyName,
                reason: 'missing_required',
            })
            continue
        }

        if (!canCoerceToType(value, propertyType)) {
            errors.push({
                propertyName,
                reason: 'type_mismatch',
                expectedType: propertyType,
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
        if (enforcedSchemas.size === 0) {
            return ok(input)
        }

        // O(1) lookup by event name
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
                                expectedType: err.expectedType,
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
