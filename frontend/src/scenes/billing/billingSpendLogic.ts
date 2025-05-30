import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateMapping, toParams } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'

import { BillingType, DateMappingOption } from '~/types'

import { canAccessBilling } from './billing-utils'
import { billingLogic } from './billingLogic'
import type { billingSpendLogicType } from './billingSpendLogicType'

export interface BillingSpendResponse {
    status: 'ok'
    type: 'timeseries'
    customer_id: string
    results: Array<{
        id: number
        label: string
        data: number[]
        dates: string[]
        breakdown_type: 'type' | 'team' | 'multiple' | null
        breakdown_value: string | string[] | null
    }>
    next?: string
}

export interface BillingSpendFilters {
    usage_types?: string[]
    team_ids?: number[]
    breakdowns?: ('type' | 'team')[]
    interval?: 'day' | 'week' | 'month'
}

export const DEFAULT_BILLING_SPEND_FILTERS: BillingSpendFilters = {
    usage_types: [],
    team_ids: [],
    breakdowns: ['type'],
    interval: 'day',
}

export interface BillingSpendLogicProps {
    dashboardItemId?: string
}

export const billingSpendLogic = kea<billingSpendLogicType>([
    path(['scenes', 'billing', 'billingSpendLogic']),
    props({} as BillingSpendLogicProps),
    key(({ dashboardItemId }) => dashboardItemId || 'global_spend'),
    connect({
        values: [organizationLogic, ['currentOrganization'], billingLogic, ['billing']],
    }),
    actions({
        setFilters: (filters: Partial<BillingSpendFilters>) => ({ filters }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        toggleSeries: (id: number) => ({ id }),
        toggleAllSeries: true,
        setExcludeEmptySeries: (exclude: boolean) => ({ exclude }),
        toggleBreakdown: (dimension: 'type' | 'team') => ({ dimension }),
    }),
    loaders(({ values }) => ({
        billingSpendResponse: [
            null as BillingSpendResponse | null,
            {
                loadBillingSpend: async () => {
                    if (!canAccessBilling(values.currentOrganization)) {
                        return null
                    }
                    const { usage_types, team_ids, breakdowns, interval } = values.filters
                    const params = {
                        ...(usage_types && usage_types.length > 0 ? { usage_types: JSON.stringify(usage_types) } : {}),
                        ...(team_ids && team_ids.length > 0 ? { team_ids: JSON.stringify(team_ids) } : {}),
                        ...(breakdowns && breakdowns.length > 0 ? { breakdowns: JSON.stringify(breakdowns) } : {}),
                        start_date:
                            values.dateFrom || dayjs().subtract(1, 'month').subtract(1, 'day').format('YYYY-MM-DD'),
                        end_date: values.dateTo || dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
                        ...(interval ? { interval } : {}),
                    }
                    try {
                        const response = await api.get(`api/billing/spend/?${toParams(params)}`)
                        return response
                    } catch (error) {
                        lemonToast.error('Failed to load billing spend, please try again or contact support.')
                        throw error
                    }
                },
            },
        ],
    })),
    reducers({
        filters: [
            { ...DEFAULT_BILLING_SPEND_FILTERS } as BillingSpendFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                toggleBreakdown: (state: BillingSpendFilters, { dimension }: { dimension: 'type' | 'team' }) => {
                    const current = state.breakdowns || []
                    const next = current.includes(dimension)
                        ? current.filter((d) => d !== dimension)
                        : [...current, dimension]
                    return { ...state, breakdowns: next }
                },
            },
        ],
        dateFrom: [
            dayjs().subtract(1, 'month').subtract(1, 'day').format('YYYY-MM-DD'),
            {
                setDateRange: (_, { dateFrom }) =>
                    dateFrom || dayjs().subtract(1, 'month').subtract(1, 'day').format('YYYY-MM-DD'),
            },
        ],
        dateTo: [
            dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
            {
                setDateRange: (_, { dateTo }) => dateTo || dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
            },
        ],
        userHiddenSeries: [
            [] as number[],
            {
                toggleSeries: (state: number[], { id }: { id: number }) =>
                    state.includes(id) ? state.filter((i) => i !== id) : [...state, id],
            },
        ],
        excludeEmptySeries: [false, { setExcludeEmptySeries: (_, { exclude }: { exclude: boolean }) => exclude }],
    }),
    selectors({
        series: [
            (s) => [s.billingSpendResponse],
            (response: BillingSpendResponse | null) => {
                if (!response?.results) {
                    return []
                }

                return response.results
            },
        ],
        dates: [
            (s) => [s.billingSpendResponse],
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
        emptySeriesIDs: [
            (s) => [s.series],
            (series: billingSpendLogicType['values']['series']) =>
                series
                    .filter((item) => item.data.reduce((a: number, b: number) => a + b, 0) === 0)
                    .map((item) => item.id),
        ],
        finalHiddenSeries: [
            (s) => [s.userHiddenSeries, s.excludeEmptySeries, s.emptySeriesIDs],
            (userHiddenSeries: number[], excludeEmptySeries: boolean, emptySeriesIDs: number[]) =>
                excludeEmptySeries ? Array.from(new Set([...userHiddenSeries, ...emptySeriesIDs])) : userHiddenSeries,
        ],
        showSeries: [
            (s) => [s.billingSpendResponseLoading, s.series],
            (billingSpendResponseLoading: boolean, series: billingSpendLogicType['values']['series']) =>
                billingSpendResponseLoading || series.length > 0,
        ],
        showEmptyState: [
            (s) => [s.showSeries, s.billingSpendResponse],
            (showSeries: boolean, billingSpendResponse: BillingSpendResponse | null) =>
                !showSeries && !!billingSpendResponse,
        ],
        heading: [
            (s) => [s.filters],
            (filters: BillingSpendFilters): string => {
                const { interval, breakdowns } = filters
                let headingText = ''
                if (interval === 'day') {
                    headingText = 'Daily'
                } else if (interval === 'week') {
                    headingText = 'Weekly'
                } else if (interval === 'month') {
                    headingText = 'Monthly'
                }
                headingText += ' spend'

                const breakdownParts: string[] = []
                if (breakdowns?.includes('type')) {
                    breakdownParts.push('product')
                }
                if (breakdowns?.includes('team')) {
                    breakdownParts.push('project')
                }

                if (breakdownParts.length > 0) {
                    headingText += ` by ${breakdownParts.join(' and ')}`
                }
                return headingText
            },
        ],
        headingTooltip: [
            (s) => [s.dateTo],
            (dateTo: string): string | null => {
                if (!dayjs(dateTo).isBefore(dayjs(), 'day')) {
                    return 'Spend is reported on a daily basis so the figures for the current day (UTC) are not available.'
                }
                return null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setFilters: async (_payload, breakpoint) => {
            await breakpoint(300)
            actions.loadBillingSpend()
        },
        setDateRange: async (_payload, breakpoint) => {
            await breakpoint(300)
            actions.loadBillingSpend()
        },
        toggleAllSeries: () => {
            const { series, excludeEmptySeries, userHiddenSeries } = values
            const potentiallyVisible = excludeEmptySeries
                ? series.filter((s) => s.data.reduce((a, b) => a + b, 0) > 0)
                : series
            const ids = potentiallyVisible.map((s) => s.id)
            const isAllVisible = ids.length > 0 && ids.every((id) => !userHiddenSeries.includes(id))
            if (isAllVisible) {
                // Hide all series
                ids.forEach((id) => actions.toggleSeries(id))
            } else {
                // Show all series
                userHiddenSeries.forEach((id) => actions.toggleSeries(id))
            }
        },
        toggleBreakdown: async (_payload, breakpoint) => {
            await breakpoint(300)
            actions.loadBillingSpend()
        },
    })),
    afterMount((logic: billingSpendLogicType) => {
        logic.actions.loadBillingSpend()
    }),
])
