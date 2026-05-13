import { expectLogic } from 'kea-test-utils'

import { quickFiltersLogic, quickFiltersSectionLogic } from 'lib/components/QuickFilters'

import { useMocks } from '~/mocks/jest'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator, QuickFilterOption } from '~/types'

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

    it('emits an event property filter for event-typed quick filters', () => {
        quickFiltersSectionLogic({ context: QuickFilterContext.Dashboards }).actions.setQuickFilterValue(
            'filter-event',
            '$environment',
            exactOption
        )

        expect(logic.values.quickFilterPropertyFiltersById['filter-event']).toEqual({
            type: PropertyFilterType.Event,
            key: '$environment',
            value: 'production',
            operator: PropertyOperator.Exact,
        })
    })

    it('emits a group property filter with group_type_index for group-typed quick filters', () => {
        quickFiltersSectionLogic({ context: QuickFilterContext.Dashboards }).actions.setQuickFilterValue(
            'filter-group',
            'plan',
            groupOption
        )

        expect(logic.values.quickFilterPropertyFiltersById['filter-group']).toEqual({
            type: PropertyFilterType.Group,
            key: 'plan',
            value: 'paid',
            operator: PropertyOperator.Exact,
            group_type_index: 0,
        })
    })

    it('falls back to event property filter when property_type is omitted (legacy quick filters)', () => {
        quickFiltersSectionLogic({ context: QuickFilterContext.Dashboards }).actions.setQuickFilterValue(
            'filter-legacy',
            '$browser',
            exactOption
        )

        expect(logic.values.quickFilterPropertyFiltersById['filter-legacy']).toEqual({
            type: PropertyFilterType.Event,
            key: '$browser',
            value: 'production',
            operator: PropertyOperator.Exact,
        })
    })
})
