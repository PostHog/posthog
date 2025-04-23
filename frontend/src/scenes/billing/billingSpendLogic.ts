import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { toParams } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'

import type { billingSpendLogicType } from './billingSpendLogicType' // Renamed type import

// Assuming the response structure is the same for spend
export interface BillingSpendResponse {
    // Renamed interface
    status: 'ok'
    type: 'timeseries'
    results: Array<{
        id: number
        label: string
        data: number[] // Should these be numbers (cents) or floats? Assuming number for now based on PRD.
        dates: string[]
        breakdown_type: 'type' | 'team' | 'multiple' | null
        breakdown_value: string | string[] | null
        compare_label?: string
        count?: number // Does count make sense for spend? Keeping for consistency, maybe backend omits it.
    }>
    next?: string
}

// Removed usage_type
export interface BillingSpendFilters {
    // Renamed interface
    breakdowns?: string[]
    show_values_on_series?: boolean // Is this relevant for spend? Keeping for now.
}

// Removed usage_type
export const DEFAULT_BILLING_SPEND_FILTERS: BillingSpendFilters = {
    // Renamed const
    breakdowns: ['type', 'team'], // Default breakdown for spend? Keeping type+team for now.
}

export interface BillingSpendLogicProps {
    // Renamed interface
    dashboardItemId?: string
}

export const billingSpendLogic = kea<billingSpendLogicType>([
    // Renamed logic
    path(['scenes', 'billing', 'billingSpendLogic']), // Updated path
    props({} as BillingSpendLogicProps),
    key(({ dashboardItemId }) => dashboardItemId || 'global_spend'), // Updated key
    connect({
        values: [organizationLogic, ['currentOrganization']],
    }),
    actions({
        setFilters: (filters: Partial<BillingSpendFilters>) => ({ filters }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
    }),
    loaders(({ values }) => ({
        billingSpendResponse: [
            // Renamed loader
            null as BillingSpendResponse | null,
            {
                loadBillingSpend: async () => {
                    // Renamed action
                    // Removed usage_type from filters destructuring and params
                    const { show_values_on_series, breakdowns } = values.filters
                    const params = {
                        ...(show_values_on_series ? { show_values_on_series } : {}),
                        ...(breakdowns ? { breakdowns: JSON.stringify(breakdowns) } : {}), // Ensure breakdowns are stringified
                        start_date: values.dateFrom || dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
                        end_date: values.dateTo || dayjs().format('YYYY-MM-DD'),
                        organization_id: values.currentOrganization?.id,
                    }
                    // Changed API endpoint
                    const response = await api.get(`api/billing/spend/?${toParams(params)}`)
                    return response
                },
            },
        ],
    })),
    reducers({
        filters: [
            // Initialize with default spend filters
            { ...DEFAULT_BILLING_SPEND_FILTERS } as BillingSpendFilters,
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
            (s) => [s.billingSpendResponse], // Use spend response
            (response: BillingSpendResponse | null) => {
                if (!response?.results) {
                    return []
                }

                // Assuming data structure is the same, if not, adjust mapping here
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
            (s) => [s.billingSpendResponse], // Use spend response
            (response: BillingSpendResponse | null) => response?.results?.[0]?.dates || [],
        ],
    }),
    listeners(({ actions }) => ({
        setFilters: () => {
            actions.loadBillingSpend() // Use spend action
        },
        setDateRange: () => {
            actions.loadBillingSpend() // Use spend action
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBillingSpend() // Use spend action
    }),
])
