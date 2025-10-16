import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import difference from 'lodash.difference'
import sortBy from 'lodash.sortby'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateMapping, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { Params } from 'scenes/sceneTypes'

import { DateMappingOption, OrganizationType } from '~/types'

import type { BillingPeriodMarker } from './BillingLineGraph'
import {
    buildTrackingProperties,
    calculateBillingPeriodMarkers,
    canAccessBilling,
    syncBillingSearchParams,
    updateBillingSearchParams,
} from './billing-utils'
import { billingLogic } from './billingLogic'
import type { billingUsageLogicType } from './billingUsageLogicType'
import type { BillingFilters } from './types'

// These date filters return correct data but there's an issue with filter label after selecting it, showing 'No date range override' instead
const TEMPORARILY_EXCLUDED_DATE_FILTER_OPTIONS = ['This month', 'Year to date', 'All time']

export enum BillingUsageResponseBreakdownType {
    TYPE = 'type',
    TEAM = 'team',
    MULTIPLE = 'multiple',
}

export interface BillingUsageResponse {
    status: 'ok'
    type: 'timeseries'
    customer_id: string
    results: Array<{
        id: number
        label: string
        data: number[]
        dates: string[]
        breakdown_type: BillingUsageResponseBreakdownType | null
        breakdown_value: string | string[] | null
    }>
    team_id_options?: number[]
    next?: string
}

export const DEFAULT_BILLING_USAGE_FILTERS: BillingFilters = {
    breakdowns: ['type'],
    usage_types: [],
    team_ids: [],
    interval: 'day',
}

export const DEFAULT_BILLING_USAGE_DATE_FROM = dayjs().subtract(1, 'month').subtract(1, 'day').format('YYYY-MM-DD')
export const DEFAULT_BILLING_USAGE_DATE_TO = dayjs().subtract(1, 'day').format('YYYY-MM-DD')

export interface BillingUsageLogicProps {
    dashboardItemId?: string
    initialFilters?: BillingFilters
    dateFrom?: string
    dateTo?: string
    syncWithUrl?: boolean // Default false - only intended on usage and spend pages
}

export const billingUsageLogic = kea<billingUsageLogicType>([
    path(['scenes', 'billing', 'billingUsageLogic']),
    props({} as BillingUsageLogicProps),
    key(({ dashboardItemId }) => dashboardItemId || 'global'),
    connect(() => ({
        values: [
            organizationLogic,
            ['currentOrganization'],
            billingLogic,
            ['billing', 'billingPeriodUTC'],
            preflightLogic,
            ['isHobby'],
        ],
        actions: [eventUsageLogic, ['reportBillingUsageInteraction']],
    })),
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
        toggleTeamBreakdown: true,
        resetFilters: true,
    }),
    loaders(({ values }) => ({
        billingUsageResponse: [
            null as BillingUsageResponse | null,
            {
                loadBillingUsage: async () => {
                    if (!canAccessBilling(values.currentOrganization) || values.isHobby) {
                        return null
                    }
                    const { usage_types, team_ids, breakdowns, interval } = values.filters
                    const params = {
                        ...(usage_types && usage_types.length > 0 ? { usage_types: JSON.stringify(usage_types) } : {}),
                        ...(team_ids && team_ids.length > 0 ? { team_ids: JSON.stringify(team_ids) } : {}),
                        ...(breakdowns && breakdowns.length > 0 ? { breakdowns: JSON.stringify(breakdowns) } : {}),
                        start_date: values.dateFrom,
                        end_date: values.dateTo,
                        ...(interval ? { interval } : {}),
                    }
                    try {
                        return await api.get(`api/billing/usage/?${toParams(params)}`)
                    } catch (error) {
                        lemonToast.error('Failed to load billing usage. Please try again or contact support.')
                        throw error
                    }
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        filters: [
            { ...(props.initialFilters || DEFAULT_BILLING_USAGE_FILTERS) },
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                toggleTeamBreakdown: (state: BillingFilters) => {
                    // Always toggle only 'team' in breakdowns, preserving 'type'
                    const current: ('type' | 'team')[] = state.breakdowns ?? []
                    const hasTeam = current.includes('team')
                    const next: ('type' | 'team')[] = hasTeam
                        ? current.filter((d) => d !== 'team')
                        : [...current, 'team']
                    return { ...state, breakdowns: next }
                },
                resetFilters: () => ({ ...(props.initialFilters || DEFAULT_BILLING_USAGE_FILTERS) }),
            },
        ],
        dateFrom: [
            props.dateFrom || DEFAULT_BILLING_USAGE_DATE_FROM,
            {
                setDateRange: (_, { dateFrom }) => dateFrom || props.dateFrom || DEFAULT_BILLING_USAGE_DATE_FROM,
                resetFilters: () => props.dateFrom || DEFAULT_BILLING_USAGE_DATE_FROM,
            },
        ],
        dateTo: [
            props.dateTo || DEFAULT_BILLING_USAGE_DATE_TO,
            {
                setDateRange: (_, { dateTo }) => dateTo || props.dateTo || DEFAULT_BILLING_USAGE_DATE_TO,
                resetFilters: () => props.dateTo || DEFAULT_BILLING_USAGE_DATE_TO,
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
                resetFilters: () => false,
            },
        ],
    })),
    selectors({
        dateOptions: [
            (s) => [s.billingPeriodUTC],
            (currentPeriod): DateMappingOption[] => {
                const currentBillingPeriodStart = currentPeriod.start
                const currentBillingPeriodEnd = currentPeriod.end
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
                const dayAndMonthOptions = dateMapping.filter(
                    (o) => o.defaultInterval !== 'hour' && !TEMPORARILY_EXCLUDED_DATE_FILTER_OPTIONS.includes(o.key)
                )
                return [currentBillingPeriodOption, previousBillingPeriodOption, ...dayAndMonthOptions]
            },
        ],
        billingPeriodMarkers: [
            (s) => [s.billingPeriodUTC, s.dateFrom, s.dateTo],
            (currentPeriod, dateFrom: string, dateTo: string): BillingPeriodMarker[] => {
                return calculateBillingPeriodMarkers(currentPeriod, dateFrom, dateTo)
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
        showSeries: [
            (s) => [s.billingUsageResponseLoading, s.series],
            (billingUsageResponseLoading: boolean, series: billingUsageLogicType['values']['series']) =>
                billingUsageResponseLoading || series.length > 0,
        ],
        showEmptyState: [
            (s) => [s.showSeries, s.billingUsageResponse],
            (showSeries: boolean, billingUsageResponse: BillingUsageResponse | null) =>
                !showSeries && !!billingUsageResponse,
        ],
        heading: [
            (s) => [s.filters],
            (filters: BillingFilters): string => {
                const { interval, breakdowns } = filters
                let heading = ''
                if (interval === 'day') {
                    heading = 'Daily'
                } else if (interval === 'week') {
                    heading = 'Weekly'
                } else if (interval === 'month') {
                    heading = 'Monthly'
                }
                heading += ' usage'

                const breakdownParts: string[] = []
                if (breakdowns?.includes('type')) {
                    breakdownParts.push('product')
                }
                if (breakdowns?.includes('team')) {
                    breakdownParts.push('project')
                }

                if (breakdownParts.length > 0) {
                    heading += ` by ${breakdownParts.join(' and ')}`
                }
                return heading
            },
        ],
        headingTooltip: [
            (s) => [s.dateTo],
            (dateTo: string): string | null => {
                if (!dayjs(dateTo).isBefore(dayjs(), 'day')) {
                    return 'Usage is reported on a daily basis so the figures for the current day (UTC) are not available.'
                }
                return null
            },
        ],
        teamOptions: [
            (s) => [s.currentOrganization, s.billingUsageResponse],
            (currentOrganization: OrganizationType | null, billingUsageResponse: BillingUsageResponse | null) => {
                const liveTeams = currentOrganization?.teams || []
                const liveTeamIds = liveTeams.map((team) => team.id)
                const liveOptions = sortBy(
                    liveTeams.map((team) => ({ key: String(team.id), label: team.name })),
                    'label'
                )

                const teamIdOptions = billingUsageResponse?.team_id_options || []

                const deletedTeamIds = difference(teamIdOptions, liveTeamIds)
                const deletedOptions = sortBy(deletedTeamIds).map((teamId: number) => ({
                    key: String(teamId),
                    label: `ID: ${teamId} (deleted)`,
                }))

                return [...liveOptions, ...deletedOptions]
            },
        ],
    }),

    actionToUrl(({ values, props }) => {
        const buildURL = (): [string, Params, Record<string, any>, { replace: boolean }] => {
            const keepCurrentUrl: [string, Params, Record<string, any>, { replace: boolean }] = [
                router.values.location.pathname,
                router.values.searchParams,
                router.values.hashParams,
                { replace: false },
            ]

            if (props.syncWithUrl !== true) {
                return keepCurrentUrl
            }

            return syncBillingSearchParams(router, (params: Params) => {
                updateBillingSearchParams(
                    params,
                    'usage_types',
                    values.filters.usage_types,
                    DEFAULT_BILLING_USAGE_FILTERS.usage_types
                )
                updateBillingSearchParams(
                    params,
                    'team_ids',
                    values.filters.team_ids,
                    DEFAULT_BILLING_USAGE_FILTERS.team_ids
                )
                updateBillingSearchParams(
                    params,
                    'breakdowns',
                    values.filters.breakdowns,
                    DEFAULT_BILLING_USAGE_FILTERS.breakdowns
                )
                updateBillingSearchParams(
                    params,
                    'interval',
                    values.filters.interval,
                    DEFAULT_BILLING_USAGE_FILTERS.interval
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
            toggleTeamBreakdown: () => buildURL(),
            resetFilters: () => buildURL(),
        }
    }),

    urlToAction(({ actions, values, props }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (props.syncWithUrl !== true) {
                return
            }

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
                actions.reportBillingUsageInteraction(buildTrackingProperties('filters_changed', values))
            }
            actions.loadBillingUsage()
        },
        setDateRange: async ({ shouldDebounce }, breakpoint) => {
            if (shouldDebounce) {
                await breakpoint(200)
                actions.reportBillingUsageInteraction(buildTrackingProperties('date_changed', values))
            }
            actions.loadBillingUsage()
        },
        resetFilters: async () => {
            actions.reportBillingUsageInteraction(buildTrackingProperties('filters_cleared', values))
            actions.loadBillingUsage()
        },
        toggleAllSeries: () => {
            const { series, excludeEmptySeries, userHiddenSeries } = values
            const potentiallyVisible = excludeEmptySeries
                ? series.filter((s) => s.data.reduce((a, b) => a + b, 0) > 0)
                : series
            const ids = potentiallyVisible.map((s) => s.id)
            const isAllVisible = ids.length > 0 && ids.every((id) => !userHiddenSeries.includes(id))
            actions.reportBillingUsageInteraction(buildTrackingProperties('series_toggled', values))

            if (isAllVisible) {
                // Hide all series
                ids.forEach((id) => actions.toggleSeries(id))
            } else {
                // Show all series
                userHiddenSeries.forEach((id) => actions.toggleSeries(id))
            }
        },
        toggleTeamBreakdown: async (_payload, breakpoint) => {
            await breakpoint(200)
            actions.reportBillingUsageInteraction(buildTrackingProperties('breakdown_toggled', values))
            actions.loadBillingUsage()
        },
    })),
    afterMount(({ actions }: billingUsageLogicType) => {
        actions.loadBillingUsage()
    }),
])
