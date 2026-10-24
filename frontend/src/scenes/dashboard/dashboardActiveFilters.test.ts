import { DashboardFilter } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { getDashboardActiveFilters } from './dashboardActiveFilters'

const emailFilter = {
    key: 'email',
    type: PropertyFilterType.Person,
    value: 'a@example.com',
    operator: PropertyOperator.Exact,
} as const

describe('getDashboardActiveFilters', () => {
    const cases: Array<[string, DashboardFilter, string[]]> = [
        ['no overrides', {}, []],
        ['date range and explicit date stay on the bar', { date_from: '-7d', explicitDate: true }, []],
        ['inherit values are not overrides', { interval: null, filterTestAccounts: null, compareFilter: null }, []],
        ['empty breakdown object from the picker', { breakdown_filter: {} }, []],
        ['empty breakdowns list', { breakdown_filter: { breakdowns: [] } }, []],
        ['incomplete property filter', { properties: [{} as any, emailFilter] }, ['property:1']],
        [
            'every override, in bar order',
            {
                properties: [emailFilter],
                breakdown_filter: { breakdowns: [{ property: '$browser' }] },
                interval: 'week',
                filterTestAccounts: false,
                compareFilter: { compare: true },
            },
            ['property:0', 'breakdown', 'interval', 'testAccounts', 'compare'],
        ],
        ['test accounts forced on', { filterTestAccounts: true }, ['testAccounts']],
        ['comparison turned off is still an override', { compareFilter: { compare: false } }, ['compare']],
    ]

    test.each(cases)('%s', (_, filters, expected) => {
        const active = getDashboardActiveFilters(filters).map((filter) =>
            filter.kind === 'property' ? `property:${filter.index}` : filter.kind
        )
        expect(active).toEqual(expected)
    })
})
