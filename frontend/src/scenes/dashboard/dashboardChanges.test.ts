import type { HogQLVariable } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { getDashboardFilterChanges, getDashboardVariableChanges } from './dashboardChanges'

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
                previousValue: ['browser = Chrome'],
                value: ['browser = Firefox'],
                status: 'changed',
            },
            { label: 'Property filter', previousValue: [], value: ['country = Canada'], status: 'new' },
            { label: 'Property filter', previousValue: ['os = macOS'], value: [], status: 'removed' },
        ])
    })

    it('groups date changes into one change', () => {
        expect(getDashboardFilterChanges({}, { date_from: '-1d' })).toEqual([
            { label: 'Date range', previousValue: [], value: ['Last 1 day'], status: 'new' },
        ])
    })

    it('lists an explicit property-filter clear', () => {
        expect(getDashboardFilterChanges({}, { properties: [] })).toEqual([
            { label: 'Property filters', previousValue: [], value: ['No property filters'], status: 'new' },
        ])
    })
})

describe('getDashboardVariableChanges', () => {
    it('lists each SQL variable change against its saved or default value', () => {
        const variable = (variableId: string, value: string): HogQLVariable => ({
            code_name: variableId,
            variableId,
            value,
            isNull: false,
        })

        expect(
            getDashboardVariableChanges(
                { saved: variable('saved', 'before') },
                {
                    saved: variable('saved', 'after'),
                    first: variable('first', 'one'),
                    second: variable('second', 'two'),
                },
                {
                    first: variable('first', 'default one'),
                    second: variable('second', 'default two'),
                }
            )
        ).toEqual([
            { label: 'saved', previousValue: ['before'], value: ['after'], status: 'changed' },
            { label: 'first', previousValue: ['default one'], value: ['one'], status: 'changed' },
            { label: 'second', previousValue: ['default two'], value: ['two'], status: 'changed' },
        ])
    })
})
