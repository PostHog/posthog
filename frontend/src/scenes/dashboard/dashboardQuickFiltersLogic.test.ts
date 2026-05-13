import { expectLogic } from 'kea-test-utils'

import { quickFiltersLogic, quickFiltersSectionLogic } from 'lib/components/QuickFilters'

import { useMocks } from '~/mocks/jest'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, QuickFilterOption } from '~/types'

import { dashboardQuickFiltersLogic } from './dashboardQuickFiltersLogic'

const exactOption: QuickFilterOption = {
    id: 'opt-1',
    value: 'production',
    label: 'Production',
    operator: PropertyOperator.Exact,
}

const groupOption: QuickFilterOption = {
    id: 'opt-paid',
    value: 'paid',
    label: 'Paid',
    operator: PropertyOperator.Exact,
}

const mockQuickFilters = [
    {
        id: 'filter-event',
        name: 'Environment',
        property_name: '$environment',
        property_type: 'event',
        group_type_index: null,
        type: 'manual-options',
        options: [exactOption],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-group',
        name: 'Customer plan',
        property_name: 'plan',
        property_type: 'group',
        group_type_index: 0,
        type: 'manual-options',
        options: [groupOption],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-legacy',
        name: 'Legacy (no property_type)',
        property_name: '$browser',
        type: 'manual-options',
        options: [exactOption],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-group-missing-index',
        name: 'Plan (missing group_type_index — legacy row)',
        property_name: 'plan',
        property_type: 'group',
        group_type_index: null,
        type: 'manual-options',
        options: [groupOption],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
]

type Case = {
    name: string
    filterId: string
    propertyName: string
    option: QuickFilterOption
    expected: AnyPropertyFilter | null
}

const CASES: readonly Case[] = [
    {
        name: 'event-typed quick filter emits an event property filter',
        filterId: 'filter-event',
        propertyName: '$environment',
        option: exactOption,
        expected: {
            type: PropertyFilterType.Event,
            key: '$environment',
            value: 'production',
            operator: PropertyOperator.Exact,
        },
    },
    {
        name: 'group-typed quick filter emits a group property filter with group_type_index',
        filterId: 'filter-group',
        propertyName: 'plan',
        option: groupOption,
        expected: {
            type: PropertyFilterType.Group,
            key: 'plan',
            value: 'paid',
            operator: PropertyOperator.Exact,
            group_type_index: 0,
        },
    },
    {
        name: 'legacy quick filter without property_type falls back to event',
        filterId: 'filter-legacy',
        propertyName: '$browser',
        option: exactOption,
        expected: {
            type: PropertyFilterType.Event,
            key: '$browser',
            value: 'production',
            operator: PropertyOperator.Exact,
        },
    },
    {
        name: 'group-typed filter with missing group_type_index is skipped (defensive guard)',
        filterId: 'filter-group-missing-index',
        propertyName: 'plan',
        option: groupOption,
        expected: null,
    },
]

describe('dashboardQuickFiltersLogic', () => {
    let logic: ReturnType<typeof dashboardQuickFiltersLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: mockQuickFilters },
            },
        })
        initKeaTests()

        const context = QuickFilterContext.Dashboards
        const filtersLogic = quickFiltersLogic({ context })
        filtersLogic.mount()
        await expectLogic(filtersLogic).toFinishAllListeners()

        quickFiltersSectionLogic({ context }).mount()
        logic = dashboardQuickFiltersLogic()
        logic.mount()
    })

    it.each(CASES)('$name', ({ filterId, propertyName, option, expected }) => {
        quickFiltersSectionLogic({ context: QuickFilterContext.Dashboards }).actions.setQuickFilterValue(
            filterId,
            propertyName,
            option
        )

        const actual = logic.values.quickFilterPropertyFiltersById[filterId]
        if (expected === null) {
            expect(actual).toBeUndefined()
        } else {
            expect(actual).toEqual(expected)
        }
    })
})
