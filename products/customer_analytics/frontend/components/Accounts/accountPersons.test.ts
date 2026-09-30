import { PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    DEFAULT_PERSONS_SORTING,
    MAX_PERSON_PROPERTY_COLUMNS,
    completePersonPropertyFilters,
    parsePersistedPersonsConfig,
    personEmail,
    personPropertyDisplayValue,
    propertyColumnKey,
} from './accountPersons'

const filter = (overrides: Partial<PersonPropertyFilter>): PersonPropertyFilter => ({
    type: PropertyFilterType.Person,
    key: 'plan',
    operator: PropertyOperator.Exact,
    value: ['pro'],
    ...overrides,
})

describe('accountPersons', () => {
    describe('personEmail', () => {
        it.each([
            ['a valid address', { email: ' ada@example.com ' }, 'ada@example.com'],
            // The API drops restricted properties, so a hidden email arrives as a missing key.
            ['a missing email', {}, null],
            ['a null email', { email: null }, null],
            ['a blank email', { email: '   ' }, null],
            ['a non-string email', { email: 42 }, null],
        ])('handles %s', (_, properties, expected) => {
            expect(personEmail({ properties })).toBe(expected)
        })
    })

    describe('completePersonPropertyFilters', () => {
        it.each([
            ['a value', true, filter({ value: ['pro'] })],
            ['an empty value list', false, filter({ value: [] })],
            ['no value', false, filter({ value: undefined })],
            ['an empty string', false, filter({ value: '' })],
            ['zero', true, filter({ value: 0 })],
            ['is set without a value', true, filter({ operator: PropertyOperator.IsSet, value: undefined })],
            ['no key', false, filter({ key: '' })],
        ])('a filter with %s is complete: %s', (_name, complete, candidate) => {
            expect(completePersonPropertyFilters([candidate])).toHaveLength(complete ? 1 : 0)
        })
    })

    describe('parsePersistedPersonsConfig', () => {
        it('falls back to defaults for missing or malformed config', () => {
            expect(parsePersistedPersonsConfig(undefined)).toEqual({
                searchTerm: '',
                sorting: DEFAULT_PERSONS_SORTING,
                propertyColumns: [],
                propertyFilters: [],
            })
            expect(
                parsePersistedPersonsConfig({
                    searchTerm: 5,
                    sorting: { columnKey: 3, order: 9 },
                    propertyColumns: 'plan',
                    propertyFilters: [null, { type: 'event', key: 'x' }],
                })
            ).toEqual(parsePersistedPersonsConfig(undefined))
        })

        it('bounds and de-duplicates saved columns and never keeps email as an extra column', () => {
            const many = Array.from({ length: MAX_PERSON_PROPERTY_COLUMNS + 3 }, (_, index) => `prop_${index}`)

            const { propertyColumns } = parsePersistedPersonsConfig({ propertyColumns: ['email', 'prop_0', ...many] })

            expect(propertyColumns).toHaveLength(MAX_PERSON_PROPERTY_COLUMNS)
            expect(propertyColumns).not.toContain('email')
        })

        it('keeps a saved sort only when its column is available', () => {
            const sorting = { columnKey: propertyColumnKey('plan'), order: 1 }

            expect(parsePersistedPersonsConfig({ sorting }).sorting).toEqual(DEFAULT_PERSONS_SORTING)
            expect(parsePersistedPersonsConfig({ sorting, propertyColumns: ['plan'] }).sorting).toEqual(sorting)
        })
    })

    describe('personPropertyDisplayValue', () => {
        it.each([
            [null, null],
            [undefined, null],
            ['', null],
            ['pro', 'pro'],
            [0, '0'],
            [false, 'false'],
            [{ a: 1 }, '{"a":1}'],
            [['x', 'y'], '["x","y"]'],
        ])('renders %j as %j', (value, expected) => {
            expect(personPropertyDisplayValue(value)).toBe(expected)
        })
    })
})
