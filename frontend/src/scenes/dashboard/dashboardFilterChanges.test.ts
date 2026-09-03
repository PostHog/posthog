import { PropertyFilterType, PropertyOperator } from '~/types'

import { getDashboardFilterChanges } from './dashboardFilterChanges'

describe('getDashboardFilterChanges', () => {
    it('lists new, changed, and removed property filters with their values', () => {
        expect(
            getDashboardFilterChanges(
                {
                    properties: [
                        {
                            key: 'browser',
                            type: PropertyFilterType.Event,
                            operator: PropertyOperator.Exact,
                            value: 'Chrome',
                        },
                        {
                            key: 'os',
                            type: PropertyFilterType.Event,
                            operator: PropertyOperator.Exact,
                            value: 'macOS',
                        },
                    ],
                },
                {
                    properties: [
                        {
                            key: 'browser',
                            type: PropertyFilterType.Event,
                            operator: PropertyOperator.Exact,
                            value: 'Firefox',
                        },
                        {
                            key: 'country',
                            type: PropertyFilterType.Event,
                            operator: PropertyOperator.Exact,
                            value: 'Canada',
                        },
                    ],
                }
            )
        ).toEqual([
            {
                label: 'Property filter',
                previousValue: 'browser is Chrome',
                value: 'browser is Firefox',
                status: 'changed',
            },
            { label: 'Property filter', value: 'country is Canada', status: 'new' },
            { label: 'Property filter', previousValue: 'os is macOS', status: 'removed' },
        ])
    })

    it('groups date changes into one change', () => {
        expect(getDashboardFilterChanges({}, { date_from: '-1d' })).toEqual([
            { label: 'Date range', value: 'Last 24 hours', status: 'new' },
        ])
    })

    it('lists an explicit property-filter clear', () => {
        expect(getDashboardFilterChanges({}, { properties: [] })).toEqual([
            { label: 'Property filters', value: 'No property filters', status: 'new' },
        ])
    })
})
