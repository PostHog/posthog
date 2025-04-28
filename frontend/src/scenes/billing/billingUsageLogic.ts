import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateMapping, toParams } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'

import { BillingType, DateMappingOption } from '~/types'

import { billingLogic } from './billingLogic'
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
    usage_types?: string[]
    team_ids?: number[]
    breakdowns?: ('type' | 'team')[]
    show_values_on_series?: boolean
}

export const DEFAULT_BILLING_USAGE_FILTERS: BillingUsageFilters = {
    breakdowns: ['type'],
    usage_types: [],
    team_ids: [],
}

export interface BillingUsageLogicProps {
    dashboardItemId?: string
}

export const billingUsageLogic = kea<billingUsageLogicType>([
    path(['scenes', 'billing', 'billingUsageLogic']),
    props({} as BillingUsageLogicProps),
    key(({ dashboardItemId }) => dashboardItemId || 'global'),
    connect({
        values: [organizationLogic, ['currentOrganization'], billingLogic, ['billing']],
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
                    const { usage_types, team_ids, show_values_on_series, breakdowns } = values.filters
                    const params = {
                        ...(usage_types && usage_types.length > 0 ? { usage_types: JSON.stringify(usage_types) } : {}),
                        ...(team_ids && team_ids.length > 0 ? { team_ids: JSON.stringify(team_ids) } : {}),
                        ...(show_values_on_series ? { show_values_on_series } : {}),
                        ...(breakdowns && breakdowns.length > 0 ? { breakdowns: JSON.stringify(breakdowns) } : {}),
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
