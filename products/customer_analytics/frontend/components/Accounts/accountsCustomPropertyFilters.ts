import { isUUIDLike } from 'lib/utils/guards'

import { escapeHogQLString, escapePropertyAsHogQLIdentifier } from '~/queries/utils'
import { AccountCustomPropertyFilter, PropertyOperator, PropertyType } from '~/types'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertyDisplayTypeEnumApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

export function propertyTypeForDisplayType(displayType: CustomPropertyDisplayTypeEnumApi): PropertyType {
    switch (displayType) {
        case 'number':
        case 'currency':
        case 'percent':
            return PropertyType.Numeric
        case 'boolean':
            return PropertyType.Boolean
        case 'date':
        case 'datetime':
            return PropertyType.DateTime
        default:
            return PropertyType.String
    }
}

// Only the operators the expression builder below can compile — keeps the operator
// dropdown in sync with what the query can actually run (e.g. no semver operators).
export const ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST: PropertyOperator[] = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.IContains,
    PropertyOperator.NotIContains,
    PropertyOperator.Regex,
    PropertyOperator.NotRegex,
    PropertyOperator.GreaterThan,
    PropertyOperator.GreaterThanOrEqual,
    PropertyOperator.LessThan,
    PropertyOperator.LessThanOrEqual,
    PropertyOperator.IsSet,
    PropertyOperator.IsNotSet,
    PropertyOperator.IsDateExact,
    PropertyOperator.IsDateBefore,
    PropertyOperator.IsDateAfter,
]

const RANGE_OPERATOR_SYMBOLS: Partial<Record<PropertyOperator, string>> = {
    [PropertyOperator.GreaterThan]: '>',
    [PropertyOperator.GreaterThanOrEqual]: '>=',
    [PropertyOperator.LessThan]: '<',
    [PropertyOperator.LessThanOrEqual]: '<=',
}

const DATE_OPERATOR_SYMBOLS: Partial<Record<PropertyOperator, string>> = {
    [PropertyOperator.IsDateExact]: '=',
    [PropertyOperator.IsDateBefore]: '<',
    [PropertyOperator.IsDateAfter]: '>',
}

function normalizeFilterValues(filter: AccountCustomPropertyFilter): (string | number)[] {
    const raw = Array.isArray(filter.value) ? filter.value : filter.value == null ? [] : [filter.value]
    return raw.filter((value): value is string | number => value !== '' && value !== null && value !== undefined)
}

// The join yields NULL for accounts where the property is unset, and a bare negation
// propagates it (NULL → row excluded) — but "is not X" must keep accounts with no value
// at all. Same fix as posthog/hogql/property.py wrapping NOT_REGEX in ifNull(..., 1).
function includeUnset(predicate: string): string {
    return `ifNull(${predicate}, true)`
}

// The join coalesces the boolean column to a string, but whether that renders as
// 'true'/'false' or '1'/'0' depends on the federated engine — match either, the same
// hedge the boolean cell renderer uses.
const BOOLEAN_LITERALS: Record<string, string[]> = {
    true: ["'true'", "'1'"],
    '1': ["'true'", "'1'"],
    false: ["'false'", "'0'"],
    '0': ["'false'", "'0'"],
}

function booleanLiterals(values: (string | number)[]): string[] {
    return [...new Set(values.flatMap((value) => BOOLEAN_LITERALS[String(value).toLowerCase()] ?? []))]
}

// The join coalesces every value to a string, so equality/ILIKE work on the column directly;
// numeric and date comparisons re-type it (toFloatOrNull / parseDateTimeBestEffort) —
// the same casts the overview tiles use for aggregation.
export function customPropertyFilterToExpression(
    filter: AccountCustomPropertyFilter,
    definition: CustomPropertyDefinitionApi
): string | null {
    // The key round-trips through saved views and the URL hash before landing in raw HogQL,
    // so only ever interpolate a validated UUID (the shared escaper is defense in depth).
    if (!filter.key || !isUUIDLike(filter.key)) {
        return null
    }
    const column = `accounts.custom_properties.values.${escapePropertyAsHogQLIdentifier(filter.key)}`
    const operator = filter.operator

    if (operator === PropertyOperator.IsSet) {
        return `${column} IS NOT NULL`
    }
    if (operator === PropertyOperator.IsNotSet) {
        return `${column} IS NULL`
    }

    const values = normalizeFilterValues(filter)
    if (values.length === 0) {
        return null
    }
    const propertyType = propertyTypeForDisplayType(definition.display_type)

    switch (operator) {
        case PropertyOperator.Exact:
        case PropertyOperator.IsNot: {
            const negated = operator === PropertyOperator.IsNot
            if (propertyType === PropertyType.Numeric) {
                const numbers = values.map(Number).filter(Number.isFinite)
                if (numbers.length === 0) {
                    return null
                }
                const target = `toFloatOrNull(${column})`
                const comparison =
                    numbers.length === 1
                        ? `${target} ${negated ? '!=' : '='} ${numbers[0]}`
                        : `${target} ${negated ? 'NOT IN' : 'IN'} (${numbers.join(', ')})`
                return negated ? includeUnset(comparison) : comparison
            }
            const literals =
                propertyType === PropertyType.Boolean
                    ? booleanLiterals(values)
                    : values.map((value) => escapeHogQLString(String(value)))
            if (literals.length === 0) {
                return null
            }
            const comparison =
                literals.length === 1
                    ? `${column} ${negated ? '!=' : '='} ${literals[0]}`
                    : `${column} ${negated ? 'NOT IN' : 'IN'} (${literals.join(', ')})`
            return negated ? includeUnset(comparison) : comparison
        }
        case PropertyOperator.IContains:
        case PropertyOperator.NotIContains: {
            // Several values match "contains any of them" (so the negation is "contains none"),
            // mirroring posthog/hogql/property.py's multi-value search semantics.
            const anyMatch = values.map((value) => `${column} ILIKE ${escapeHogQLString(`%${value}%`)}`).join(' OR ')
            if (operator === PropertyOperator.NotIContains) {
                return includeUnset(`NOT (${anyMatch})`)
            }
            return values.length === 1 ? anyMatch : `(${anyMatch})`
        }
        case PropertyOperator.Regex:
        case PropertyOperator.NotRegex: {
            const anyMatch = values.map((value) => `match(${column}, ${escapeHogQLString(String(value))})`).join(' OR ')
            if (operator === PropertyOperator.NotRegex) {
                return includeUnset(`NOT (${anyMatch})`)
            }
            return values.length === 1 ? anyMatch : `(${anyMatch})`
        }
        case PropertyOperator.GreaterThan:
        case PropertyOperator.GreaterThanOrEqual:
        case PropertyOperator.LessThan:
        case PropertyOperator.LessThanOrEqual: {
            const threshold = Number(values[0])
            if (!Number.isFinite(threshold)) {
                return null
            }
            return `toFloatOrNull(${column}) ${RANGE_OPERATOR_SYMBOLS[operator]} ${threshold}`
        }
        case PropertyOperator.IsDateExact:
        case PropertyOperator.IsDateBefore:
        case PropertyOperator.IsDateAfter:
            // parseDateTimeBestEffort is the HogQL name (it maps to the ClickHouse
            // ...OrNull variant); the OrNull-suffixed name isn't registered in HogQL.
            return `parseDateTimeBestEffort(${column}) ${
                DATE_OPERATOR_SYMBOLS[operator]
            } parseDateTimeBestEffort(${escapeHogQLString(String(values[0]))})`
        default:
            return null
    }
}

/** One HogQL predicate per compilable filter; filters for deleted definitions or with
 * incomplete values are dropped rather than breaking the query. */
export function customPropertyFiltersToExpressions(
    filters: AccountCustomPropertyFilter[],
    definitionsById: Record<string, CustomPropertyDefinitionApi>
): string[] {
    return filters
        .map((filter) => {
            const definition = filter.key ? definitionsById[filter.key] : undefined
            return definition ? customPropertyFilterToExpression(filter, definition) : null
        })
        .filter((expression): expression is string => !!expression)
}
