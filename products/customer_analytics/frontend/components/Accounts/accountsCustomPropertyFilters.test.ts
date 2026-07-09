import { AccountCustomPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customPropertyFiltersToExpressions, customPropertyFilterToExpression } from './accountsCustomPropertyFilters'

const TEXT_ID = '11111111-2222-3333-4444-555555555555'
const NUMBER_ID = '66666666-7777-8888-9999-aaaaaaaaaaaa'

function definition(overrides: Partial<CustomPropertyDefinitionApi>): CustomPropertyDefinitionApi {
    return { id: TEXT_ID, name: 'Prop', display_type: 'text', ...overrides } as CustomPropertyDefinitionApi
}

function filter(overrides: Partial<AccountCustomPropertyFilter>): AccountCustomPropertyFilter {
    return {
        type: PropertyFilterType.AccountCustomProperty,
        key: TEXT_ID,
        operator: PropertyOperator.Exact,
        ...overrides,
    }
}

// The shared identifier escaper double-quotes the (non-simple) UUID key.
const TEXT_COLUMN = `accounts.custom_properties.values."${TEXT_ID}"`
const NUMBER_COLUMN = `accounts.custom_properties.values."${NUMBER_ID}"`

describe('accountsCustomPropertyFilters', () => {
    it.each([
        ['text exact', 'text', { value: 'Enterprise' }, `${TEXT_COLUMN} = 'Enterprise'`],
        ['escapes quotes and backslashes', 'text', { value: "O'Brien \\ co" }, `${TEXT_COLUMN} = 'O\\'Brien \\\\ co'`],
        ['exact with multiple values', 'text', { value: ['a', 'b'] }, `${TEXT_COLUMN} IN ('a', 'b')`],
        // Negative operators keep accounts where the property is unset (the join yields NULL there).
        [
            'is_not includes unset accounts',
            'text',
            { operator: PropertyOperator.IsNot, value: 'Churned' },
            `ifNull(${TEXT_COLUMN} != 'Churned', true)`,
        ],
        [
            'is_not with multiple values',
            'text',
            { operator: PropertyOperator.IsNot, value: ['a', 'b'] },
            `ifNull(${TEXT_COLUMN} NOT IN ('a', 'b'), true)`,
        ],
        ['icontains', 'text', { operator: PropertyOperator.IContains, value: 'acme' }, `${TEXT_COLUMN} ILIKE '%acme%'`],
        [
            'icontains matches any of multiple values',
            'text',
            { operator: PropertyOperator.IContains, value: ['acme', 'beta'] },
            `(${TEXT_COLUMN} ILIKE '%acme%' OR ${TEXT_COLUMN} ILIKE '%beta%')`,
        ],
        [
            'not_icontains includes unset accounts',
            'text',
            { operator: PropertyOperator.NotIContains, value: 'acme' },
            `ifNull(NOT (${TEXT_COLUMN} ILIKE '%acme%'), true)`,
        ],
        [
            'not_icontains matches none of multiple values',
            'text',
            { operator: PropertyOperator.NotIContains, value: ['acme', 'beta'] },
            `ifNull(NOT (${TEXT_COLUMN} ILIKE '%acme%' OR ${TEXT_COLUMN} ILIKE '%beta%'), true)`,
        ],
        ['regex', 'text', { operator: PropertyOperator.Regex, value: '^acme' }, `match(${TEXT_COLUMN}, '^acme')`],
        [
            'not_regex includes unset accounts',
            'text',
            { operator: PropertyOperator.NotRegex, value: '^acme' },
            `ifNull(NOT (match(${TEXT_COLUMN}, '^acme')), true)`,
        ],
        ['is_set', 'text', { operator: PropertyOperator.IsSet, value: null }, `${TEXT_COLUMN} IS NOT NULL`],
        ['is_not_set', 'text', { operator: PropertyOperator.IsNotSet, value: null }, `${TEXT_COLUMN} IS NULL`],
        [
            'select equality compares the stored label',
            'select',
            { value: 'Enterprise' },
            `${TEXT_COLUMN} = 'Enterprise'`,
        ],
        // Booleans match both string renderings of the stored bool ('true'/'false' and '1'/'0').
        ['boolean exact matches either rendering', 'boolean', { value: 'true' }, `${TEXT_COLUMN} IN ('true', '1')`],
        ['boolean false', 'boolean', { value: 'false' }, `${TEXT_COLUMN} IN ('false', '0')`],
        [
            'boolean is_not includes unset accounts',
            'boolean',
            { operator: PropertyOperator.IsNot, value: 'true' },
            `ifNull(${TEXT_COLUMN} NOT IN ('true', '1'), true)`,
        ],
        ['numeric exact casts the column', 'number', { value: '42' }, `toFloatOrNull(${TEXT_COLUMN}) = 42`],
        ['numeric multi-value IN', 'currency', { value: [10, '20.5'] }, `toFloatOrNull(${TEXT_COLUMN}) IN (10, 20.5)`],
        [
            'numeric is_not includes unset accounts',
            'number',
            { operator: PropertyOperator.IsNot, value: '42' },
            `ifNull(toFloatOrNull(${TEXT_COLUMN}) != 42, true)`,
        ],
        [
            'numeric greater than',
            'percent',
            { operator: PropertyOperator.GreaterThan, value: '0.8' },
            `toFloatOrNull(${TEXT_COLUMN}) > 0.8`,
        ],
        [
            'date before',
            'date',
            { operator: PropertyOperator.IsDateBefore, value: '2026-01-15' },
            `parseDateTimeBestEffort(${TEXT_COLUMN}) < parseDateTimeBestEffort('2026-01-15')`,
        ],
        [
            'datetime exact',
            'datetime',
            { operator: PropertyOperator.IsDateExact, value: '2026-01-15 10:00:00' },
            `parseDateTimeBestEffort(${TEXT_COLUMN}) = parseDateTimeBestEffort('2026-01-15 10:00:00')`,
        ],
    ])('%s', (_name, displayType, filterOverrides, expected) => {
        expect(
            customPropertyFilterToExpression(
                filter(filterOverrides as Partial<AccountCustomPropertyFilter>),
                definition({ display_type: displayType as CustomPropertyDefinitionApi['display_type'] })
            )
        ).toBe(expected)
    })

    it.each([
        ['missing value', 'number', { value: null }],
        ['empty string value', 'number', { value: '' }],
        ['non-UUID key never reaches the query', 'number', { key: 'accounts.name); DROP', value: 'x' }],
        ['numeric operator with non-numeric value', 'number', { operator: PropertyOperator.GreaterThan, value: 'abc' }],
        ['boolean with an unrecognized value', 'boolean', { value: 'maybe' }],
    ])('returns null for %s', (_name, displayType, filterOverrides) => {
        expect(
            customPropertyFilterToExpression(
                filter(filterOverrides as Partial<AccountCustomPropertyFilter>),
                definition({ display_type: displayType as CustomPropertyDefinitionApi['display_type'] })
            )
        ).toBeNull()
    })

    it('drops filters for unknown definitions and keeps compilable ones', () => {
        const definitionsById = { [NUMBER_ID]: definition({ id: NUMBER_ID, display_type: 'number' }) }
        const expressions = customPropertyFiltersToExpressions(
            [
                filter({ key: NUMBER_ID, operator: PropertyOperator.LessThanOrEqual, value: 5 }),
                filter({ key: TEXT_ID, value: 'orphaned' }),
            ],
            definitionsById
        )
        expect(expressions).toEqual([`toFloatOrNull(${NUMBER_COLUMN}) <= 5`])
    })
})
