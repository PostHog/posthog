import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateMapping, toParams } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'

import type { OrganizationType } from '~/types'
import { BillingType, DateMappingOption } from '~/types'

import { billingLogic } from './billingLogic'
import type { billingUsageLogicType } from './billingUsageLogicType'
import { ALL_USAGE_TYPES } from './constants'

export interface BillingUsageResponse {
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

export interface BillingUsageFilters {
    usage_types?: string[]
    team_ids?: number[]
    breakdowns?: ('type' | 'team')[]
    interval?: 'day' | 'week' | 'month'
}

export const DEFAULT_BILLING_USAGE_FILTERS: BillingUsageFilters = {
    breakdowns: ['type'],
    usage_types: [],
    team_ids: [],
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
        values: [organizationLogic, ['currentOrganization'], billingLogic, ['billing']],
    }),
    subscriptions((logic: billingUsageLogicType) => ({
        currentOrganization: (org: OrganizationType | null, prevOrg: OrganizationType | null) => {
            if (!prevOrg && org) {
                // patch only team_ids
                const teamIds: number[] = org.teams?.map(({ id }) => id) ?? []
                if (teamIds.length) {
                    logic.actions.setFilters({ team_ids: teamIds })
                }
            }
        },
    })),
    actions({
        setFilters: (filters: Partial<BillingUsageFilters>) => ({ filters }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        toggleSeries: (id: number) => ({ id }),
        toggleAllSeries: true,
        setExcludeEmptySeries: (exclude: boolean) => ({ exclude }),
        toggleTeamBreakdown: true,
    }),
    loaders(({ values }) => ({
        billingUsageResponse: [
            null as BillingUsageResponse | null,
            {
                loadBillingUsage: async () => {
                    const { usage_types, team_ids, breakdowns, interval } = values.filters
                    const params = {
                        ...(usage_types && usage_types.length > 0 ? { usage_types: JSON.stringify(usage_types) } : {}),
                        ...(team_ids && team_ids.length > 0 ? { team_ids: JSON.stringify(team_ids) } : {}),
                        ...(breakdowns && breakdowns.length > 0 ? { breakdowns: JSON.stringify(breakdowns) } : {}),
                        start_date: values.dateFrom || dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
                        end_date: values.dateTo || dayjs().format('YYYY-MM-DD'),
                        ...(interval ? { interval } : {}),
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
                toggleTeamBreakdown: (state: BillingUsageFilters) => {
                    // Always toggle only 'team' in breakdowns, preserving 'type'
                    const current: ('type' | 'team')[] = state.breakdowns ?? []
                    const hasTeam = current.includes('team')
                    const next: ('type' | 'team')[] = hasTeam
                        ? current.filter((d) => d !== 'team')
                        : [...current, 'team']
                    return { ...state, breakdowns: next }
                },
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
        userHiddenSeries: [
            [] as number[],
            {
                toggleSeries: (state: number[], { id }: { id: number }) =>
                    state.includes(id) ? state.filter((i: number) => i !== id) : [...state, id],
            },
        ],
        excludeEmptySeries: [
            false,
            {
                setExcludeEmptySeries: (_, { exclude }: { exclude: boolean }) => exclude,
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

                return response.results
            },
        ],
        dates: [
            (s) => [s.billingUsageResponse],
            (response: BillingUsageResponse | null) => response?.results?.[0]?.dates || [],
        ],
        emptySeriesIDs: [
            (s) => [s.series],
            (series: billingUsageLogicType['values']['series']) =>
                series
                    .filter((item) => item.data.reduce((a: number, b: number) => a + b, 0) === 0)
                    .map((item) => item.id),
        ],
        finalHiddenSeries: [
            (s) => [s.userHiddenSeries, s.excludeEmptySeries, s.emptySeriesIDs],
            (userHiddenSeries: number[], excludeEmptySeries: boolean, emptySeriesIDs: number[]) =>
                excludeEmptySeries ? Array.from(new Set([...userHiddenSeries, ...emptySeriesIDs])) : userHiddenSeries,
        ],
    }),
    listeners(({ actions, values }) => ({
        setFilters: async (_payload, breakpoint) => {
            await breakpoint(300)
            actions.loadBillingUsage()
        },
        setDateRange: async (_payload, breakpoint) => {
            await breakpoint(300)
            actions.loadBillingUsage()
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
        toggleTeamBreakdown: async (_payload, breakpoint) => {
            await breakpoint(300)
            actions.loadBillingUsage()
        },
    })),
    afterMount(({ values, actions }: billingUsageLogicType) => {
        const org = values.currentOrganization
        if (org) {
            // const teamIds: number[] = org.teams?.map(({ id }) => id) || []
            const teamIds = [30393, 33266]
            actions.setFilters({ usage_types: ALL_USAGE_TYPES, team_ids: teamIds })
        }
    }),
])
