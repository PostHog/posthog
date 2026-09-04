import { DashboardFilter, TileFilters } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { clearsSavedDashboardFilter, isDashboardFilterEmpty } from './dashboardFilterEmpty'

describe('isDashboardFilterEmpty', () => {
    const emptyCases: Array<[string, DashboardFilter | TileFilters | null | undefined]> = [
        ['null', null],
        ['undefined', undefined],
        ['empty object', {}],
        ['only explicitDate false', { explicitDate: false }],
        ['null date fields + explicitDate false', { date_from: null, date_to: null, explicitDate: false }],
        ['empty properties array', { properties: [] }],
        ['filterTestAccounts null', { filterTestAccounts: null }],
        ['ignoreDashboardFilters false', { ignoreDashboardFilters: false }],
    ]

    test.each(emptyCases)('returns true for %s', (_, filter) => {
        expect(isDashboardFilterEmpty(filter)).toBe(true)
    })

    const nonEmptyCases: Array<[string, DashboardFilter | TileFilters]> = [
        ['date_from set', { date_from: '-7d' }],
        ['date_to set', { date_to: '2024-01-01' }],
        [
            'non-empty properties',
            {
                properties: [
                    {
                        key: 'email',
                        type: PropertyFilterType.Person,
                        value: 'foo',
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
        ],
        ['breakdown_filter set', { breakdown_filter: { breakdown: 'browser' } }],
        ['interval set', { interval: 'week' }],
        ['filterTestAccounts forced on', { filterTestAccounts: true }],
        ['filterTestAccounts forced off', { filterTestAccounts: false }],
        ['ignoreDashboardFilters set', { ignoreDashboardFilters: true }],
    ]

    test.each(nonEmptyCases)('returns false for %s', (_, filter) => {
        expect(isDashboardFilterEmpty(filter)).toBe(false)
    })
})

describe('clearsSavedDashboardFilter', () => {
    const SAVED: DashboardFilter = {
        date_from: '-30d',
        date_to: null,
        properties: [{ key: 'email', type: PropertyFilterType.Person, value: 'foo', operator: PropertyOperator.Exact }],
    }

    const cases: Array<[string, DashboardFilter, DashboardFilter | null, boolean]> = [
        ['a saved date range switched off', { date_from: null, date_to: null }, SAVED, true],
        ['saved properties switched off', { properties: [] }, SAVED, true],
        ['a payload that mentions no filter at all', {}, SAVED, false],
        ['a filter the dashboard has not saved', { interval: null }, SAVED, false],
        ['a date range switched off with nothing saved', { date_from: null, date_to: null }, null, false],
        ['a saved date range replaced rather than switched off', { date_from: '-7d', date_to: null }, SAVED, false],
    ]

    test.each(cases)('reports %s', (_, filter, savedFilters, expected) => {
        expect(clearsSavedDashboardFilter(filter, savedFilters)).toBe(expected)
    })
})
