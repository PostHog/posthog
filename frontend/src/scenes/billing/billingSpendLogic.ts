import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateMapping, toParams } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'

import { BillingType, DateMappingOption } from '~/types'

import { billingLogic } from './billingLogic'
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

// Added usage_types and team_ids
export interface BillingSpendFilters {
    // Renamed interface
    usage_types?: string[] // Added
    team_ids?: number[] // Added
    breakdowns?: ('type' | 'team')[] // Changed type to match usage
    show_values_on_series?: boolean // Is this relevant for spend? Keeping for now.
}

// Added usage_types and team_ids, adjusted default breakdown to just type
export const DEFAULT_BILLING_SPEND_FILTERS: BillingSpendFilters = {
    // Renamed const
    usage_types: [], // Added, initialize empty
    team_ids: [], // Added, initialize empty
    breakdowns: ['type'], // Default breakdown for spend now matches usage
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
        values: [organizationLogic, ['currentOrganization'], billingLogic, ['billing']],
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
                    // Added usage_types and team_ids to filters destructuring and params
                    const { usage_types, team_ids, show_values_on_series, breakdowns } = values.filters
                    const params = {
                        ...(usage_types && usage_types.length > 0 ? { usage_types: JSON.stringify(usage_types) } : {}), // Added
                        ...(team_ids && team_ids.length > 0 ? { team_ids: JSON.stringify(team_ids) } : {}), // Added
                        ...(show_values_on_series ? { show_values_on_series } : {}),
                        ...(breakdowns && breakdowns.length > 0 ? { breakdowns: JSON.stringify(breakdowns) } : {}), // Ensure breakdowns are stringified
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
        dateOptions: [
            (s) => [s.billing],
            (billing: BillingType | null): DateMappingOption[] => {
                const currentBillingPeriodStart = billing?.billing_period?.current_period_start
                const currentBillingPeriodEnd = billing?.billing_period?.current_period_end
                const currentBillingPeriodOption: DateMappingOption = {
                    key: 'Current billing period',
                    values: [
                        currentBillingPeriodStart?.format('YYYY-MM-DD') || '',
                        currentBillingPeriodEnd?.format('YYYY-MM-DD') || '',
                    ],
                    defaultInterval: 'day',
                }
                const previousBillingPeriodOption: DateMappingOption = {
                    key: 'Previous billing period',
                    values: [
                        currentBillingPeriodStart?.subtract(1, 'month').format('YYYY-MM-DD') || '',
                        currentBillingPeriodEnd?.subtract(1, 'month').format('YYYY-MM-DD') || '',
                    ],
                }
                const dayAndMonthOptions = dateMapping.filter((o) => o.defaultInterval !== 'hour')
                return [currentBillingPeriodOption, previousBillingPeriodOption, ...dayAndMonthOptions]
            },
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
