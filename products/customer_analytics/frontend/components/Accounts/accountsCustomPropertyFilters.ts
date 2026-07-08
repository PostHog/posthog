import { isUUIDLike } from 'lib/utils/guards'

import { escapeHogQLString } from '~/queries/utils'
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

// The join coalesces every value to a string, so equality/ILIKE work on the column directly;
// numeric and date comparisons re-type it (toFloatOrNull / parseDateTimeBestEffortOrNull) —
// the same casts the overview tiles use for aggregation.
export function customPropertyFilterToExpression(
    filter: AccountCustomPropertyFilter,
    definition: CustomPropertyDefinitionApi
): string | null {
    // The key round-trips through saved views and the URL hash before landing in raw HogQL,
    // so only ever interpolate a validated UUID.
    if (!filter.key || !isUUIDLike(filter.key)) {
        return null
    }
    const column = `accounts.custom_properties.values.\`${filter.key}\``
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
            if (propertyType === PropertyType.Numeric) {
                const numbers = values.map(Number).filter(Number.isFinite)
                if (numbers.length === 0) {
                    return null
                }
                const target = `toFloatOrNull(${column})`
                return numbers.length === 1
                    ? `${target} ${operator === PropertyOperator.Exact ? '=' : '!='} ${numbers[0]}`
                    : `${target} ${operator === PropertyOperator.Exact ? 'IN' : 'NOT IN'} (${numbers.join(', ')})`
            }
            const literals = values.map((value) => escapeHogQLString(String(value)))
            return literals.length === 1
                ? `${column} ${operator === PropertyOperator.Exact ? '=' : '!='} ${literals[0]}`
                : `${column} ${operator === PropertyOperator.Exact ? 'IN' : 'NOT IN'} (${literals.join(', ')})`
        }
        case PropertyOperator.IContains:
            return `${column} ILIKE ${escapeHogQLString(`%${values[0]}%`)}`
        case PropertyOperator.NotIContains:
            return `NOT (${column} ILIKE ${escapeHogQLString(`%${values[0]}%`)})`
        case PropertyOperator.Regex:
            return `match(${column}, ${escapeHogQLString(String(values[0]))})`
        case PropertyOperator.NotRegex:
            return `NOT match(${column}, ${escapeHogQLString(String(values[0]))})`
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
            return `parseDateTimeBestEffortOrNull(${column}) ${
                DATE_OPERATOR_SYMBOLS[operator]
            } parseDateTimeBestEffortOrNull(${escapeHogQLString(String(values[0]))})`
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
