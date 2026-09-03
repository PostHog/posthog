import { DashboardFilter, DashboardFilterView } from '~/types'

import { searchParamsWithUrlFilters } from './dashboardUtils'

export interface DashboardFilterViewAnalyticsProperties {
    has_date_filter: boolean
    property_filter_count: number
    has_breakdown_filter: boolean
    has_interval_filter: boolean
    has_test_account_filter: boolean
}

export function createDashboardFilterView(id: string, name: string, filters: DashboardFilter): DashboardFilterView {
    return { id, name: name.trim(), filters }
}

export function dashboardFilterViewSearchParams(
    searchParams: Record<string, unknown>,
    activeViewId: string | undefined,
    view: DashboardFilterView
): Record<string, unknown> {
    return searchParamsWithUrlFilters(searchParams, activeViewId === view.id ? {} : view.filters)
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
