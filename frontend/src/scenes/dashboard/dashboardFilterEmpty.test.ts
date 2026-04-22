import { DashboardFilter, TileFilters } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { isDashboardFilterEmpty } from './dashboardFilterEmpty'

describe('isDashboardFilterEmpty', () => {
    const emptyCases: Array<[string, DashboardFilter | TileFilters | null | undefined]> = [
        ['null', null],
        ['undefined', undefined],
        ['empty object', {}],
        ['only explicitDate false', { explicitDate: false }],
        ['null date fields + explicitDate false', { date_from: null, date_to: null, explicitDate: false }],
        ['empty properties array', { properties: [] }],
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
    ]

    test.each(nonEmptyCases)('returns false for %s', (_, filter) => {
        expect(isDashboardFilterEmpty(filter)).toBe(false)
    })
})
