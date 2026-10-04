import { deepEqual } from 'fast-equals'

import { DashboardFilter } from '~/queries/schema/schema-general'
import { DashboardFilterView } from '~/types'

import { parseURLFilters, searchParamsWithUrlFilters } from './dashboardUtils'

export interface DashboardFilterViewAnalyticsProperties {
    has_date_filter: boolean
    property_filter_count: number
    has_breakdown_filter: boolean
    has_interval_filter: boolean
    has_test_account_filter: boolean
}

export const DASHBOARD_FILTER_VIEW_PARAM = 'filter_view'

export function createDashboardFilterView(id: string, name: string, filters: DashboardFilter): DashboardFilterView {
    return { id, name: name.trim(), filters }
}

export function dashboardFilterViewSearchParams(
    searchParams: Record<string, unknown>,
    activeViewId: string | undefined,
    view: DashboardFilterView
): Record<string, unknown> {
    const otherParams = { ...searchParams }
    delete otherParams[DASHBOARD_FILTER_VIEW_PARAM]
    if (activeViewId === view.id && deepEqual(parseURLFilters(searchParams), view.filters)) {
        return searchParamsWithUrlFilters(otherParams, {})
    }
    return {
        ...searchParamsWithUrlFilters(otherParams, view.filters),
        [DASHBOARD_FILTER_VIEW_PARAM]: view.id,
    }
}

export function dashboardFilterViewAnalyticsProperties(
    filters: DashboardFilter
): DashboardFilterViewAnalyticsProperties {
    return {
        has_date_filter: !!(filters.date_from || filters.date_to),
        property_filter_count: filters.properties?.length ?? 0,
        has_breakdown_filter: !!filters.breakdown_filter,
        has_interval_filter: !!filters.interval,
        has_test_account_filter: filters.filterTestAccounts !== undefined,
    }
}
