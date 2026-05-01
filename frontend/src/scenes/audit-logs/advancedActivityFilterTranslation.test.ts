import { ActivityScope, PropertyFilterType, PropertyOperator } from '~/types'

import { advancedActivityFiltersToHogProperties } from './advancedActivityFilterTranslation'
import { AdvancedActivityLogFilters, DEFAULT_START_DATE } from './advancedActivityLogsLogic'

describe('advancedActivityFiltersToHogProperties', () => {
    const baseFilter = (overrides: Partial<AdvancedActivityLogFilters> = {}): AdvancedActivityLogFilters => ({
        start_date: DEFAULT_START_DATE,
        users: [],
        scopes: [],
        activities: [],
        detail_filters: {},
        item_ids: [],
        page: 1,
        ...overrides,
    })

    it.each([
        {
            field: 'scopes',
            values: [ActivityScope.INSIGHT, ActivityScope.DASHBOARD],
            expectedKey: 'scope',
        },
        {
            field: 'activities',
            values: ['created', 'updated'],
            expectedKey: 'activity',
        },
        {
            field: 'item_ids',
            values: ['abc', 'def'],
            expectedKey: 'item_id',
        },
    ] as const)(
        'maps $field to "$expectedKey" property filter with Exact operator',
        ({ field, values, expectedKey }) => {
            const result = advancedActivityFiltersToHogProperties(
                baseFilter({ [field]: values } as Partial<AdvancedActivityLogFilters>)
            )
            expect(result.properties).toEqual([
                {
                    key: expectedKey,
                    type: PropertyFilterType.Event,
                    value: values,
                    operator: PropertyOperator.Exact,
                },
            ])
            expect(result.droppedFields).toEqual([])
        }
    )

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
                start_date: DEFAULT_START_DATE,
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
