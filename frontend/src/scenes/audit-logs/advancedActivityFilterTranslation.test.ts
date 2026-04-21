import { ActivityScope, PropertyFilterType, PropertyOperator } from '~/types'

import { advancedActivityFiltersToHogProperties } from './advancedActivityFilterTranslation'
import { AdvancedActivityLogFilters } from './advancedActivityLogsLogic'

describe('advancedActivityFiltersToHogProperties', () => {
    const baseFilter = (overrides: Partial<AdvancedActivityLogFilters> = {}): AdvancedActivityLogFilters => ({
        start_date: '-30d',
        users: [],
        scopes: [],
        activities: [],
        detail_filters: {},
        item_ids: [],
        page: 1,
        ...overrides,
    })

    it('maps scopes to a single scope property filter with Exact operator', () => {
        const result = advancedActivityFiltersToHogProperties(
            baseFilter({ scopes: [ActivityScope.INSIGHT, ActivityScope.DASHBOARD] })
        )
        expect(result.properties).toEqual([
            {
                key: 'scope',
                type: PropertyFilterType.Event,
                value: [ActivityScope.INSIGHT, ActivityScope.DASHBOARD],
                operator: PropertyOperator.Exact,
            },
        ])
        expect(result.droppedFields).toEqual([])
    })

    it('maps activities to an activity property filter', () => {
        const result = advancedActivityFiltersToHogProperties(baseFilter({ activities: ['created', 'updated'] }))
        expect(result.properties).toEqual([
            {
                key: 'activity',
                type: PropertyFilterType.Event,
                value: ['created', 'updated'],
                operator: PropertyOperator.Exact,
            },
        ])
    })

    it('maps item_ids to an item_id property filter', () => {
        const result = advancedActivityFiltersToHogProperties(baseFilter({ item_ids: ['abc', 'def'] }))
        expect(result.properties).toEqual([
            {
                key: 'item_id',
                type: PropertyFilterType.Event,
                value: ['abc', 'def'],
                operator: PropertyOperator.Exact,
            },
        ])
    })

    it('maps was_impersonated and is_system booleans', () => {
        const result = advancedActivityFiltersToHogProperties(baseFilter({ was_impersonated: true, is_system: false }))
        expect(result.properties).toEqual([
            {
                key: 'was_impersonated',
                type: PropertyFilterType.Event,
                value: ['true'],
                operator: PropertyOperator.Exact,
            },
            {
                key: 'is_system',
                type: PropertyFilterType.Event,
                value: ['false'],
                operator: PropertyOperator.Exact,
            },
        ])
    })

    it('maps whitelisted detail_filters (name, changes) with operator translation', () => {
        const result = advancedActivityFiltersToHogProperties(
            baseFilter({
                detail_filters: {
                    name: { operation: 'contains', value: 'foo' },
                    changes: { operation: 'in', value: ['added', 'removed'] },
                },
            })
        )
        expect(result.properties).toEqual(
            expect.arrayContaining([
                {
                    key: 'detail.name',
                    type: PropertyFilterType.Event,
                    value: 'foo',
                    operator: PropertyOperator.IContains,
                },
                {
                    key: 'detail.changes',
                    type: PropertyFilterType.Event,
                    value: ['added', 'removed'],
                    operator: PropertyOperator.In,
                },
            ])
        )
        expect(result.droppedFields).toEqual([])
    })

    it('drops users, date ranges, and non-whitelisted detail_filter paths', () => {
        const result = advancedActivityFiltersToHogProperties(
            baseFilter({
                users: ['u1'],
                start_date: '-30d',
                end_date: '-1d',
                detail_filters: {
                    name: { operation: 'exact', value: 'keep me' },
                    'foo.bar': { operation: 'exact', value: 'drop me' },
                },
            })
        )
        expect(result.properties).toEqual([
            {
                key: 'detail.name',
                type: PropertyFilterType.Event,
                value: 'keep me',
                operator: PropertyOperator.Exact,
            },
        ])
        expect(result.droppedFields.sort()).toEqual(['date range', 'detail.foo.bar', 'users'].sort())
    })

    it('returns an empty property list when no mappable filters are set', () => {
        const result = advancedActivityFiltersToHogProperties(baseFilter())
        expect(result.properties).toEqual([])
        expect(result.droppedFields).toEqual([])
    })
})
