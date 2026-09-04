import type { HogQLVariable } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { dashboardFiltersEqual, getDashboardFilterChanges, getDashboardVariableChanges } from './dashboardChanges'

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

    it.each([
        ['interval', { interval: null }],
        ['test accounts', { filterTestAccounts: null }],
        ['breakdown', { breakdown_filter: null }],
    ])('reports no change when %s returns to inherit', (_name, reverted) => {
        expect(getDashboardFilterChanges({}, reverted)).toEqual([])
    })

    it('still reports a change when a saved setting returns to inherit', () => {
        expect(getDashboardFilterChanges({ interval: 'week' }, { interval: null })).toEqual([
            { label: 'Grouped by', previousValue: ['Week'], value: [], status: 'removed' },
        ])
    })

    it('marks the exact time range mode on each side of a date change', () => {
        expect(
            getDashboardFilterChanges(
                { date_from: '-7d', explicitDate: true },
                { date_from: '-7d', explicitDate: false }
            )
        ).toEqual([
            {
                label: 'Date range',
                previousValue: ['Last 7 days (exact time range)'],
                value: ['Last 7 days'],
                status: 'changed',
            },
        ])
    })

    it('shows the exact time range mode when no date range is set', () => {
        expect(getDashboardFilterChanges({}, { explicitDate: true })).toEqual([
            { label: 'Date range', previousValue: [], value: ['All time (exact time range)'], status: 'new' },
        ])
    })

    it.each([
        ['excludes test accounts when the filter is turned on', true, 'Excluded'],
        ['includes test accounts when the filter is turned off', false, 'Included'],
    ])('%s', (_name, filterTestAccounts, expectedValue) => {
        expect(getDashboardFilterChanges({}, { filterTestAccounts })).toEqual([
            { label: 'Test accounts', previousValue: [], value: [expectedValue], status: 'new' },
        ])
    })

    it('lists a switch from excluded to included test accounts', () => {
        expect(getDashboardFilterChanges({ filterTestAccounts: true }, { filterTestAccounts: false })).toEqual([
            { label: 'Test accounts', previousValue: ['Excluded'], value: ['Included'], status: 'changed' },
        ])
    })

    it('lists an explicit property-filter clear', () => {
        expect(getDashboardFilterChanges({}, { properties: [] })).toEqual([
            { label: 'Property filters', previousValue: [], value: ['No property filters'], status: 'new' },
        ])
    })
})

describe('dashboardFiltersEqual', () => {
    it.each([
        ['a null interval against an absent one', {}, { interval: null }],
        ['a null test account override against an absent one', {}, { filterTestAccounts: null }],
        ['a null end date against an absent one', { date_from: '-7d' }, { date_from: '-7d', date_to: null }],
    ])('treats %s as unchanged', (_name, saved, current) => {
        expect(dashboardFiltersEqual(saved, current)).toBe(true)
    })

    it.each([
        ['a forced interval', {}, { interval: 'week' as const }],
        ['a forced test account override', {}, { filterTestAccounts: false }],
        ['a cleared property list', {}, { properties: [] }],
    ])('treats %s as changed', (_name, saved, current) => {
        expect(dashboardFiltersEqual(saved, current)).toBe(false)
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
