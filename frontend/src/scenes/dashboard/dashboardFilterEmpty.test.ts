import { DashboardFilter, TileFilters } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { isDashboardFilterEmpty } from './dashboardFilterEmpty'

describe('isDashboardFilterEmpty', () => {
    const emptyCases: Array<[string, DashboardFilter | TileFilters | null | undefined]> = [
        ['null', null],
        ['undefined', undefined],
        ['empty object', {}],
        ['only explicitDate false', { explicitDate: false }],
        ['ignoreDashboardFilters false', { ignoreDashboardFilters: false }],
    ]

    test.each(emptyCases)('returns true for %s', (_, filter) => {
        expect(isDashboardFilterEmpty(filter)).toBe(true)
    })

    const nonEmptyCases: Array<[string, DashboardFilter | TileFilters]> = [
        ['date_from set', { date_from: '-7d' }],
        ['date_to set', { date_to: '2024-01-01' }],
        ['date fields explicitly cleared', { date_from: null, date_to: null, explicitDate: false }],
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
        ['properties explicitly cleared', { properties: [] }],
        ['breakdown_filter set', { breakdown_filter: { breakdown: 'browser' } }],
        ['breakdown_filter explicitly cleared', { breakdown_filter: null }],
        ['interval set', { interval: 'week' }],
        ['interval explicitly cleared', { interval: null }],
        ['filterTestAccounts forced on', { filterTestAccounts: true }],
        ['filterTestAccounts forced off', { filterTestAccounts: false }],
        ['filterTestAccounts explicitly cleared', { filterTestAccounts: null }],
        ['ignoreDashboardFilters set', { ignoreDashboardFilters: true }],
    ]

    test.each(nonEmptyCases)('returns false for %s', (_, filter) => {
        expect(isDashboardFilterEmpty(filter)).toBe(false)
    })
})
