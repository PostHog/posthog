import { DashboardFilter } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    createDashboardFilterView,
    DASHBOARD_FILTER_VIEW_PARAM,
    dashboardFilterViewAnalyticsProperties,
    dashboardFilterViewSearchParams,
} from './dashboardFilterViewUtils'
import { parseURLFilters, SEARCH_PARAM_FILTERS_KEY } from './dashboardUtils'

const propertyFilters: NonNullable<DashboardFilter['properties']> = [
    {
        key: 'plan',
        type: PropertyFilterType.Person,
        operator: PropertyOperator.Exact,
        value: ['enterprise', 'scale'],
    },
    {
        key: '$browser',
        type: PropertyFilterType.Event,
        operator: PropertyOperator.IsNot,
        value: 'Internet Explorer',
    },
]

const combinedFilters = {
    date_from: '-30d',
    date_to: '-1d',
    explicitDate: true,
    interval: 'week' as const,
    filterTestAccounts: false,
    properties: propertyFilters,
    breakdown_filter: {
        breakdowns: [
            { property: '$browser', type: 'event' as const },
            { property: 'plan', type: 'person' as const },
            { property: 'company_id', type: 'group' as const, group_type_index: 0 },
        ],
        breakdown_limit: 25,
        breakdown_hide_other_aggregation: true,
    },
}

describe('dashboard filter views', () => {
    it('creates a view without losing any filter type', () => {
        expect(createDashboardFilterView('view-id', '  Enterprise weekly  ', combinedFilters)).toEqual({
            id: 'view-id',
            name: 'Enterprise weekly',
            filters: combinedFilters,
        })
    })

    it.each([
        ['date range and interval', { date_from: '-90d', date_to: 'now', explicitDate: true, interval: 'month' }],
        ['person and event properties', { properties: propertyFilters }],
        ['legacy event breakdown', { breakdown_filter: { breakdown: '$browser', breakdown_type: 'event' } }],
        ['multiple typed breakdowns', { breakdown_filter: combinedFilters.breakdown_filter }],
        ['test accounts included', { filterTestAccounts: true }],
        ['test accounts excluded', { filterTestAccounts: false }],
        ['all supported filter types', combinedFilters],
    ])('applies %s through the URL without changing its filter payload', (_, filters) => {
        const view = createDashboardFilterView('view-id', 'View', filters as DashboardFilter)
        const searchParams = dashboardFilterViewSearchParams({ tab: 'overview' }, undefined, view)

        expect(searchParams.tab).toBe('overview')
        expect(searchParams[DASHBOARD_FILTER_VIEW_PARAM]).toBe('view-id')
        expect(parseURLFilters(searchParams)).toEqual(filters)
    })

    it('clears the active view without removing unrelated URL state', () => {
        const view = createDashboardFilterView('view-id', 'View', combinedFilters)
        const searchParams = dashboardFilterViewSearchParams(
            {
                tab: 'overview',
                [DASHBOARD_FILTER_VIEW_PARAM]: view.id,
                [SEARCH_PARAM_FILTERS_KEY]: JSON.stringify(combinedFilters),
            },
            view.id,
            view
        )

        expect(searchParams).toEqual({ tab: 'overview' })
    })

    it('restores a selected view when the URL filters differ from its saved filters', () => {
        const view = createDashboardFilterView('view-id', 'View', combinedFilters)
        const searchParams = dashboardFilterViewSearchParams(
            {
                tab: 'overview',
                [DASHBOARD_FILTER_VIEW_PARAM]: view.id,
                [SEARCH_PARAM_FILTERS_KEY]: JSON.stringify({ date_from: '-7d' }),
            },
            view.id,
            view
        )

        expect(searchParams[DASHBOARD_FILTER_VIEW_PARAM]).toBe(view.id)
        expect(parseURLFilters(searchParams)).toEqual(combinedFilters)
    })

    it('describes every applied filter family without capturing values', () => {
        expect(dashboardFilterViewAnalyticsProperties(combinedFilters)).toEqual({
            has_date_filter: true,
            property_filter_count: 2,
            has_breakdown_filter: true,
            has_interval_filter: true,
            has_test_account_filter: true,
        })
    })
})
