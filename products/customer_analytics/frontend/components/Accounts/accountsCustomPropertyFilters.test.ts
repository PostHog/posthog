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

const TEXT_COLUMN = `accounts.custom_properties.values.\`${TEXT_ID}\``
const NUMBER_COLUMN = `accounts.custom_properties.values.\`${NUMBER_ID}\``

describe('accountsCustomPropertyFilters', () => {
    it.each([
        ['text exact', 'text', { value: 'Enterprise' }, `${TEXT_COLUMN} = 'Enterprise'`],
        ['escapes quotes and backslashes', 'text', { value: "O'Brien \\ co" }, `${TEXT_COLUMN} = 'O\\'Brien \\\\ co'`],
        ['exact with multiple values', 'text', { value: ['a', 'b'] }, `${TEXT_COLUMN} IN ('a', 'b')`],
        ['is_not', 'text', { operator: PropertyOperator.IsNot, value: 'Churned' }, `${TEXT_COLUMN} != 'Churned'`],
        ['icontains', 'text', { operator: PropertyOperator.IContains, value: 'acme' }, `${TEXT_COLUMN} ILIKE '%acme%'`],
        [
            'not_icontains',
            'text',
            { operator: PropertyOperator.NotIContains, value: 'acme' },
            `NOT (${TEXT_COLUMN} ILIKE '%acme%')`,
        ],
        ['regex', 'text', { operator: PropertyOperator.Regex, value: '^acme' }, `match(${TEXT_COLUMN}, '^acme')`],
        ['is_set', 'text', { operator: PropertyOperator.IsSet, value: null }, `${TEXT_COLUMN} IS NOT NULL`],
        ['is_not_set', 'text', { operator: PropertyOperator.IsNotSet, value: null }, `${TEXT_COLUMN} IS NULL`],
        [
            'select equality compares the stored label',
            'select',
            { value: 'Enterprise' },
            `${TEXT_COLUMN} = 'Enterprise'`,
        ],
        ['boolean exact', 'boolean', { value: 'true' }, `${TEXT_COLUMN} = 'true'`],
        ['numeric exact casts the column', 'number', { value: '42' }, `toFloatOrNull(${TEXT_COLUMN}) = 42`],
        ['numeric multi-value IN', 'currency', { value: [10, '20.5'] }, `toFloatOrNull(${TEXT_COLUMN}) IN (10, 20.5)`],
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
        ['missing value', { value: null }],
        ['empty string value', { value: '' }],
        ['non-UUID key never reaches the query', { key: 'accounts.name); DROP', value: 'x' }],
        ['numeric operator with non-numeric value', { operator: PropertyOperator.GreaterThan, value: 'abc' }],
    ])('returns null for %s', (_name, filterOverrides) => {
        expect(
            customPropertyFilterToExpression(
                filter(filterOverrides as Partial<AccountCustomPropertyFilter>),
                definition({ display_type: 'number' })
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
