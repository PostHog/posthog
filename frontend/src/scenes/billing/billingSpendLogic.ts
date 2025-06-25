import { lemonToast } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateMapping, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import difference from 'lodash.difference'
import sortBy from 'lodash.sortby'
import { organizationLogic } from 'scenes/organizationLogic'
import { Params } from 'scenes/sceneTypes'

import { BillingType, DateMappingOption, OrganizationType } from '~/types'

import {
    buildTrackingProperties,
    canAccessBilling,
    syncBillingSearchParams,
    updateBillingSearchParams,
} from './billing-utils'
import { billingLogic } from './billingLogic'
import type { billingSpendLogicType } from './billingSpendLogicType'
import type { BillingFilters } from './types'

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
    team_id_options?: number[]
    next?: string
}

export const DEFAULT_BILLING_SPEND_FILTERS: BillingFilters = {
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
        actions: [eventUsageLogic, ['reportBillingSpendInteraction']],
    }),
    actions({
        setFilters: (filters: Partial<BillingFilters>, shouldDebounce: boolean = true) => ({
            filters,
            shouldDebounce,
        }),
        setDateRange: (dateFrom: string | null, dateTo: string | null, shouldDebounce: boolean = true) => ({
            dateFrom,
            dateTo,
            shouldDebounce,
        }),
        toggleSeries: (id: number) => ({ id }),
        toggleAllSeries: true,
        setExcludeEmptySeries: (exclude: boolean, shouldDebounce: boolean = true) => ({ exclude, shouldDebounce }),
        toggleBreakdown: (dimension: 'type' | 'team') => ({ dimension }),
        resetFilters: true,
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
            { ...DEFAULT_BILLING_SPEND_FILTERS } as BillingFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                toggleBreakdown: (state: BillingFilters, { dimension }: { dimension: 'type' | 'team' }) => {
                    const current = state.breakdowns || []
                    const next = current.includes(dimension)
                        ? current.filter((d) => d !== dimension)
                        : [...current, dimension]
                    return { ...state, breakdowns: next }
                },
                resetFilters: () => ({ ...DEFAULT_BILLING_SPEND_FILTERS }),
            },
        ],
        dateFrom: [
            dayjs().subtract(1, 'month').subtract(1, 'day').format('YYYY-MM-DD'),
            {
                setDateRange: (_, { dateFrom }) =>
                    dateFrom || dayjs().subtract(1, 'month').subtract(1, 'day').format('YYYY-MM-DD'),
                resetFilters: () => dayjs().subtract(1, 'month').subtract(1, 'day').format('YYYY-MM-DD'),
            },
        ],
        dateTo: [
            dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
            {
                setDateRange: (_, { dateTo }) => dateTo || dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
                resetFilters: () => dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
            },
        ],
        userHiddenSeries: [
            [] as number[],
            {
                toggleSeries: (state: number[], { id }: { id: number }) =>
                    state.includes(id) ? state.filter((i) => i !== id) : [...state, id],
            },
        ],
        excludeEmptySeries: [
            false,
            {
                setExcludeEmptySeries: (_, { exclude }: { exclude: boolean }) => exclude,
                resetFilters: () => false,
            },
        ],
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
            (filters: BillingFilters): string => {
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
        teamOptions: [
            (s) => [s.currentOrganization, s.billingSpendResponse],
            (currentOrganization: OrganizationType | null, billingSpendResponse: BillingSpendResponse | null) => {
                const liveTeams = currentOrganization?.teams || []
                const liveTeamIds = liveTeams.map((team) => team.id)
                const liveOptions = sortBy(
                    liveTeams.map((team) => ({ key: String(team.id), label: team.name })),
                    'label'
                )

                const teamIdOptions = billingSpendResponse?.team_id_options || []

                const deletedTeamIds = difference(teamIdOptions, liveTeamIds)
                const deletedOptions = sortBy(deletedTeamIds).map((teamId: number) => ({
                    key: String(teamId),
                    label: `ID: ${teamId} (deleted)`,
                }))

                return [...liveOptions, ...deletedOptions]
            },
        ],
    }),

    actionToUrl(({ values }) => {
        const buildURL = (): [string, Params, Record<string, any>, { replace: boolean }] => {
            return syncBillingSearchParams(router, (params: Params) => {
                updateBillingSearchParams(
                    params,
                    'usage_types',
                    values.filters.usage_types,
                    DEFAULT_BILLING_SPEND_FILTERS.usage_types
                )
                updateBillingSearchParams(
                    params,
                    'team_ids',
                    values.filters.team_ids,
                    DEFAULT_BILLING_SPEND_FILTERS.team_ids
                )
                updateBillingSearchParams(
                    params,
                    'breakdowns',
                    values.filters.breakdowns,
                    DEFAULT_BILLING_SPEND_FILTERS.breakdowns
                )
                updateBillingSearchParams(
                    params,
                    'interval',
                    values.filters.interval,
                    DEFAULT_BILLING_SPEND_FILTERS.interval
                )
                updateBillingSearchParams(
                    params,
                    'date_from',
                    values.dateFrom,
                    dayjs().subtract(1, 'month').subtract(1, 'day').format('YYYY-MM-DD')
                )
                updateBillingSearchParams(
                    params,
                    'date_to',
                    values.dateTo,
                    dayjs().subtract(1, 'day').format('YYYY-MM-DD')
                )
                updateBillingSearchParams(params, 'exclude_empty', values.excludeEmptySeries, false)
                return params
            })
        }

        return {
            setFilters: () => buildURL(),
            setDateRange: () => buildURL(),
            setExcludeEmptySeries: () => buildURL(),
            toggleBreakdown: () => buildURL(),
            resetFilters: () => buildURL(),
        }
    }),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            const filtersFromUrl: Partial<BillingFilters> = {}

            if (params.usage_types && !equal(params.usage_types, values.filters.usage_types)) {
                filtersFromUrl.usage_types = params.usage_types
            }
            if (params.team_ids && !equal(params.team_ids, values.filters.team_ids)) {
                filtersFromUrl.team_ids = params.team_ids
            }
            if (params.breakdowns && !equal(params.breakdowns, values.filters.breakdowns)) {
                filtersFromUrl.breakdowns = params.breakdowns
            }
            if (params.interval && params.interval !== values.filters.interval) {
                filtersFromUrl.interval = params.interval
            }

            if (Object.keys(filtersFromUrl).length > 0) {
                actions.setFilters(filtersFromUrl, false)
            }

            if (
                (params.date_from && params.date_from !== values.dateFrom) ||
                (params.date_to && params.date_to !== values.dateTo)
            ) {
                actions.setDateRange(params.date_from || null, params.date_to || null, false)
            }

            if (params.exclude_empty !== undefined && params.exclude_empty !== values.excludeEmptySeries) {
                actions.setExcludeEmptySeries(Boolean(params.exclude_empty), false)
            }
        }

        return {
            '*': urlToAction,
        }
    }),

    listeners(({ actions, values }) => ({
        setFilters: async ({ shouldDebounce }, breakpoint) => {
            if (shouldDebounce) {
                await breakpoint(200)
                actions.reportBillingSpendInteraction(buildTrackingProperties('filters_changed', values))
            }
            actions.loadBillingSpend()
        },
        setDateRange: async ({ shouldDebounce }, breakpoint) => {
            if (shouldDebounce) {
                await breakpoint(200)
                actions.reportBillingSpendInteraction(buildTrackingProperties('date_changed', values))
            }
            actions.loadBillingSpend()
        },
        resetFilters: async () => {
            actions.reportBillingSpendInteraction(buildTrackingProperties('filters_cleared', values))
            actions.loadBillingSpend()
        },
        toggleAllSeries: () => {
            const { series, excludeEmptySeries, userHiddenSeries } = values
            const potentiallyVisible = excludeEmptySeries
                ? series.filter((s) => s.data.reduce((a, b) => a + b, 0) > 0)
                : series
            const ids = potentiallyVisible.map((s) => s.id)
            const isAllVisible = ids.length > 0 && ids.every((id) => !userHiddenSeries.includes(id))
            actions.reportBillingSpendInteraction(buildTrackingProperties('series_toggled', values))

            if (isAllVisible) {
                // Hide all series
                ids.forEach((id) => actions.toggleSeries(id))
            } else {
                // Show all series
                userHiddenSeries.forEach((id) => actions.toggleSeries(id))
            }
        },
        toggleBreakdown: async (_payload, breakpoint) => {
            await breakpoint(200)
            actions.reportBillingSpendInteraction(buildTrackingProperties('breakdown_toggled', values))
            actions.loadBillingSpend()
        },
    })),
    afterMount((logic: billingSpendLogicType) => {
        logic.actions.loadBillingSpend()
    }),
])
