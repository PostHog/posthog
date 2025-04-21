import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { toParams } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'

import type { billingUsageLogicType } from './billingUsageLogicType'

export interface BillingUsageResponse {
    status: 'ok'
    type: 'timeseries'
    results: Array<{
        id: number
        label: string
        data: number[]
        dates: string[]
        breakdown_type: 'type' | 'team' | 'multiple' | null
        breakdown_value: string | string[] | null
        compare_label?: string
        count?: number
    }>
    next?: string
}

export interface BillingUsageFilters {
    usage_type?: string
    breakdowns?: string[]
    interval?: 'day' | 'week' | 'month'
    compare?: 'previous_period'
    show_values_on_series?: boolean
}

export const DEFAULT_BILLING_USAGE_FILTERS: BillingUsageFilters = {
    breakdowns: ['type', 'team'],
    interval: 'day',
}

export interface BillingUsageLogicProps {
    dashboardItemId?: string
}

export const billingUsageLogic = kea<billingUsageLogicType>([
    path(['scenes', 'billing', 'billingUsageLogic']),
    props({} as BillingUsageLogicProps),
    key(({ dashboardItemId }) => dashboardItemId || 'global'),
    connect({
        values: [organizationLogic, ['currentOrganization']],
    }),
    actions({
        setFilters: (filters: Partial<BillingUsageFilters>) => ({ filters }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
    }),
    loaders(({ values }) => ({
        billingUsageResponse: [
            null as BillingUsageResponse | null,
            {
                loadBillingUsage: async () => {
                    const { usage_type, ...restFilters } = values.filters
                    const params = {
                        ...(usage_type ? { usage_type } : {}),
                        ...restFilters,
                        start_date: values.dateFrom || dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
                        end_date: values.dateTo || dayjs().format('YYYY-MM-DD'),
                        organization_id: values.currentOrganization?.id,
                    }
                    const response = await api.get(`api/billing/usage/?${toParams(params)}`)
                    return response
                },
            },
        ],
    })),
    reducers({
        filters: [
            // Initialize with default filters
            { ...DEFAULT_BILLING_USAGE_FILTERS } as BillingUsageFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        dateFrom: [
            dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
            {
                setDateRange: (_, { dateFrom }) => dateFrom || dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
            },
        ],
        dateTo: [
            dayjs().format('YYYY-MM-DD'),
            {
                setDateRange: (_, { dateTo }) => dateTo || dayjs().format('YYYY-MM-DD'),
            },
        ],
    }),
    selectors({
        series: [
            (s) => [s.billingUsageResponse],
            (response: BillingUsageResponse | null) => {
                if (!response?.results) {
                    return []
                }

                return response.results.map((item) => ({
                    id: item.id,
                    label: item.label,
                    data: item.data,
                    days: item.dates,
                    count: item.count || 0,
                    compare: !!item.compare_label,
                    compare_label: item.compare_label,
                    breakdown_value: item.breakdown_value || undefined,
                }))
            },
        ],
        dates: [
            (s) => [s.billingUsageResponse],
            (response: BillingUsageResponse | null) => response?.results?.[0]?.dates || [],
        ],
    }),
    listeners(({ actions }) => ({
        setFilters: () => {
            actions.loadBillingUsage()
        },
        setDateRange: () => {
            actions.loadBillingUsage()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBillingUsage()
    }),
])
