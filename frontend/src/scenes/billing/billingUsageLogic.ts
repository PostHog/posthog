import { deepEqual as equal } from 'fast-equals'
import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import type { BreakPointFunction } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import difference from 'lodash.difference'
import sortBy from 'lodash.sortby'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateMapping } from 'lib/utils/dateFilters'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { toParams } from 'lib/utils/url'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Params } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DateMappingOption, OrganizationType } from '~/types'

import type { BillingPeriod, BillingType } from '../../types'
import {
    buildTrackingProperties,
    calculateBillingPeriodMarkers,
    selectionCoversEveryProject,
    syncBillingSearchParams,
    updateBillingSearchParams,
} from './billing-utils'
import { billingLogic } from './billingLogic'
import type { BillingPeriodMarker } from './BillingPeriodMarkers'
import { DEFAULT_TOP_PROJECTS } from './constants'
import type { BillingChartType, BillingFilters } from './types'
import type { BillingUsageInteractionProps } from './types'

/** Billing reports usage a day at a time, so anything finer than a day has nothing to show.
 *
 * Checked against the interval rather than the key, so a new sub-day preset in the shared date
 * options is excluded without anyone remembering to. "Last hour" has interval 'minute', and its
 * start, `-1h`, is not a date billing can parse. */
export const SUB_DAY_DATE_FILTER_INTERVALS = ['hour', 'minute', 'second']

export function isDayOrCoarser(option: DateMappingOption): boolean {
    return !option.defaultInterval || !SUB_DAY_DATE_FILTER_INTERVALS.includes(option.defaultInterval)
}

// Billing serves at most a year per request, so the open-ended "All time" preset is not offered.
export function fitsOneRequest(option: DateMappingOption): boolean {
    return !option.values.includes('all')
}

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
    next?: string
}

const DESKTOP_USAGE_SERIES_CONVERSIONS: Record<string, { divisor: number; label: string }> = {
    posthog_code_token_credits_used_in_period: { divisor: 100, label: 'PostHog Desktop token spend (USD)' },
    sandbox_compute_credits_used_in_period: { divisor: 100, label: 'Cloud compute spend (USD)' },
    sandbox_compute_cpu_millicore_seconds_in_period: {
        divisor: 1_000,
        label: 'Cloud compute CPU (core-seconds)',
    },
    sandbox_compute_memory_mib_seconds_in_period: {
        divisor: 1_024,
        label: 'Cloud compute memory (GiB-seconds)',
    },
}

export const convertDesktopUsageSeries = (
    series: BillingUsageResponse['results'][number]
): BillingUsageResponse['results'][number] => {
    const usageType = Array.isArray(series.breakdown_value) ? series.breakdown_value[0] : series.breakdown_value
    const conversion = usageType ? DESKTOP_USAGE_SERIES_CONVERSIONS[usageType] : undefined
    const labelSeparatorIndex = series.label.lastIndexOf('::')
    const labelPrefix = labelSeparatorIndex === -1 ? '' : series.label.slice(0, labelSeparatorIndex + 2)
    return conversion
        ? {
              ...series,
              label: `${labelPrefix}${conversion.label}`,
              data: series.data.map((value) => value / conversion.divisor),
          }
        : series
}

export const DEFAULT_BILLING_USAGE_FILTERS: BillingFilters = {
    breakdowns: ['type'],
    usage_types: [],
    team_ids: [],
    interval: 'day',
    top_projects: DEFAULT_TOP_PROJECTS,
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

/**
 * Billing errors that describe something the person can change, rather than something broken.
 * These render as guidance in the page; anything else is a failure and gets an error toast.
 *
 * `usage_breakdown_too_large` means the request would need more than a billing worker holds, and
 * the guidance says what to narrow.
 */
export const ACTIONABLE_BILLING_ERROR_CODES = [
    'usage_query_timeout',
    'usage_breakdown_too_large',
    'usage_date_range_too_long',
]

export const BILLING_USAGE_QUERY_TOO_LARGE_CODE = 'usage_breakdown_too_large'

export interface BillingUsageError {
    code: string
    detail: string
}

export const getBillingUsageError = (error: unknown): BillingUsageError | null => {
    if (!error || typeof error !== 'object') {
        return null
    }

    const candidate = error as { code?: unknown; detail?: unknown }
    return typeof candidate.code === 'string' && typeof candidate.detail === 'string'
        ? { code: candidate.code, detail: candidate.detail }
        : null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface billingUsageLogicValues {
    billing: BillingType | null // billingLogic
    billingPeriodUTC: BillingPeriod // billingLogic
    canViewUsageAndSpend: boolean // billingLogic
    currentOrganization: OrganizationType | null // billingLogic
    isHobby: boolean // preflightLogic
    billingPeriodMarkers: BillingPeriodMarker[]
    billingUsageError: BillingUsageError | null
    billingUsageResponse: BillingUsageResponse | null
    billingUsageResponseLoading: boolean
    canStackSeries: boolean
    chartType: BillingChartType | null
    dateFrom: string
    dateOptions: DateMappingOption[]
    dateTo: string | null
    dates: string[]
    defaultChartType: BillingChartType
    effectiveChartType: BillingChartType
    effectiveTeamIds: number[] | undefined
    emptySeriesIDs: number[]
    excludeEmptySeries: boolean
    filters: {
        breakdowns?: ('team' | 'type')[] | undefined
        interval?: 'day' | 'month' | 'week' | undefined
        team_ids?: number[] | undefined
        top_projects?: number | null | undefined
        usage_types?: string[] | undefined
    }
    finalHiddenSeries: number[]
    heading: string
    headingTooltip: string | null
    series: {
        breakdown_type: BillingUsageResponseBreakdownType | null
        breakdown_value: string | string[] | null
        data: number[]
        dates: string[]
        id: number
        label: string
    }[]
    showEmptyState: boolean
    showSeries: boolean
    teamIdOptions: number[]
    teamIdOptionsLoading: boolean
    teamOptions: {
        key: string
        label: string
    }[]
    usageChartExportUrl: string
    usageExportUrl: string
    userHiddenSeries: number[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface billingUsageLogicActions {
    reportBillingUsageInteraction: (properties: BillingUsageInteractionProps) => {
        properties: BillingUsageInteractionProps
    } // eventUsageLogic
    loadBillingUsage: (_: void) => void
    loadBillingUsageFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadBillingUsageSuccess: (
        billingUsageResponse: BillingUsageResponse | null,
        payload?: void
    ) => {
        billingUsageResponse: BillingUsageResponse | null
        payload?: void
    }
    loadTeamIdOptions: () => any
    loadTeamIdOptionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTeamIdOptionsSuccess: (
        teamIdOptions: number[],
        payload?: any
    ) => {
        teamIdOptions: number[]
        payload?: any
    }
    resetFilters: () => {
        value: true
    }
    setBillingUsageError: (error: BillingUsageError | null) => {
        error: BillingUsageError | null
    }
    setChartType: (
        chartType: BillingChartType | null,
        shouldDebounce?: boolean
    ) => {
        chartType: BillingChartType | null
        shouldDebounce: boolean
    }
    setDateRange: (
        dateFrom: string | null,
        dateTo: string | null,
        shouldDebounce?: boolean
    ) => {
        dateFrom: string | null
        dateTo: string | null
        shouldDebounce: boolean
    }
    setExcludeEmptySeries: (
        exclude: boolean,
        shouldDebounce?: boolean
    ) => {
        exclude: boolean
        shouldDebounce: boolean
    }
    setFilters: (
        filters: Partial<BillingFilters>,
        shouldDebounce?: boolean
    ) => {
        filters: Partial<BillingFilters>
        shouldDebounce: boolean
    }
    setHiddenSeries: (ids: number[]) => {
        ids: number[]
    }
    toggleAllSeries: () => {
        value: true
    }
    toggleSeries: (id: number) => {
        id: number
    }
    toggleTeamBreakdown: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface billingUsageLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        usageExportUrl: (
            filters: {
                breakdowns?: ('team' | 'type')[] | undefined
                interval?: 'day' | 'month' | 'week' | undefined
                team_ids?: number[] | undefined
                top_projects?: number | null | undefined
                usage_types?: string[] | undefined
            },
            dateFrom: string,
            dateTo: string | null,
            effectiveTeamIds: number[] | undefined
        ) => string
        usageChartExportUrl: (
            filters: {
                breakdowns?: ('team' | 'type')[] | undefined
                interval?: 'day' | 'month' | 'week' | undefined
                team_ids?: number[] | undefined
                top_projects?: number | null | undefined
                usage_types?: string[] | undefined
            },
            dateFrom: string,
            dateTo: string | null,
            effectiveTeamIds: number[] | undefined
        ) => string
        dateOptions: (billingPeriodUTC: BillingPeriod) => DateMappingOption[]
        billingPeriodMarkers: (
            billingPeriodUTC: BillingPeriod,
            dateFrom: string,
            dateTo: string | null
        ) => BillingPeriodMarker[]
        series: (billingUsageResponse: BillingUsageResponse | null) => {
            breakdown_type: BillingUsageResponseBreakdownType | null
            breakdown_value: string | string[] | null
            data: number[]
            dates: string[]
            id: number
            label: string
        }[]
        dates: (billingUsageResponse: BillingUsageResponse | null) => string[]
        emptySeriesIDs: (
            series: {
                breakdown_type: BillingUsageResponseBreakdownType | null
                breakdown_value: string | string[] | null
                data: number[]
                dates: string[]
                id: number
                label: string
            }[]
        ) => number[]
        canStackSeries: (filters: {
            breakdowns?: ('team' | 'type')[] | undefined
            interval?: 'day' | 'month' | 'week' | undefined
            team_ids?: number[] | undefined
            top_projects?: number | null | undefined
            usage_types?: string[] | undefined
        }) => boolean
        effectiveChartType: (
            chartType: BillingChartType | null,
            defaultChartType: BillingChartType,
            canStackSeries: boolean
        ) => BillingChartType
        finalHiddenSeries: (
            userHiddenSeries: number[],
            excludeEmptySeries: boolean,
            emptySeriesIDs: number[]
        ) => number[]
        showSeries: (
            billingUsageResponseLoading: boolean,
            series: {
                breakdown_type: BillingUsageResponseBreakdownType | null
                breakdown_value: string | string[] | null
                data: number[]
                dates: string[]
                id: number
                label: string
            }[],
            billingUsageError: BillingUsageError | null
        ) => boolean
        showEmptyState: (
            showSeries: boolean,
            billingUsageResponse: BillingUsageResponse | null,
            billingUsageError: BillingUsageError | null
        ) => boolean
        heading: (filters: {
            breakdowns?: ('team' | 'type')[] | undefined
            interval?: 'day' | 'month' | 'week' | undefined
            team_ids?: number[] | undefined
            top_projects?: number | null | undefined
            usage_types?: string[] | undefined
        }) => string
        headingTooltip: (dateTo: string | null) => string | null
        effectiveTeamIds: (
            filters: {
                breakdowns?: ('team' | 'type')[] | undefined
                interval?: 'day' | 'month' | 'week' | undefined
                team_ids?: number[] | undefined
                top_projects?: number | null | undefined
                usage_types?: string[] | undefined
            },
            teamOptions: {
                key: string
                label: string
            }[]
        ) => number[] | undefined
        teamOptions: (
            currentOrganization: OrganizationType | null,
            teamIdOptions: any
        ) => {
            key: string
            label: string
        }[]
    }
}

export type billingUsageLogicType = MakeLogicType<
    billingUsageLogicValues,
    billingUsageLogicActions,
    BillingUsageLogicProps,
    billingUsageLogicMeta
>

/** The export URL for the page's filters, with or without the chart's project cap. */
function usageExportUrlFor(
    filters: BillingFilters,
    dateFrom: string,
    dateTo: string | null,
    effectiveTeamIds: number[] | undefined,
    withChartCap: boolean
): string {
    const params = {
        ...(filters.usage_types?.length ? { usage_types: JSON.stringify(filters.usage_types) } : {}),
        ...(effectiveTeamIds?.length ? { team_ids: JSON.stringify(effectiveTeamIds) } : {}),
        ...(filters.breakdowns?.length ? { breakdowns: JSON.stringify(filters.breakdowns) } : {}),
        start_date: dateFrom,
        end_date: dateTo || DEFAULT_BILLING_USAGE_DATE_TO,
        ...(filters.interval ? { interval: filters.interval } : {}),
        ...(withChartCap && filters.breakdowns?.includes('team') && filters.top_projects
            ? { top_projects: filters.top_projects }
            : {}),
    }
    return `/api/billing/usage/export/?${toParams(params)}`
}

export const billingUsageLogic = kea<billingUsageLogicType>([
    path(['scenes', 'billing', 'billingUsageLogic']),
    props({} as BillingUsageLogicProps),
    key(({ dashboardItemId }) => dashboardItemId || 'global'),
    connect(() => ({
        values: [
            billingLogic,
            ['billing', 'billingPeriodUTC', 'canViewUsageAndSpend', 'currentOrganization'],
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
        setHiddenSeries: (ids: number[]) => ({ ids }),
        toggleSeries: (id: number) => ({ id }),
        toggleAllSeries: true,
        setChartType: (chartType: BillingChartType | null, shouldDebounce: boolean = true) => ({
            chartType,
            shouldDebounce,
        }),
        setExcludeEmptySeries: (exclude: boolean, shouldDebounce: boolean = true) => ({ exclude, shouldDebounce }),
        toggleTeamBreakdown: true,
        resetFilters: true,
        setBillingUsageError: (error: BillingUsageError | null) => ({ error }),
    }),
    loaders(({ values, actions }) => ({
        teamIdOptions: [
            [] as number[],
            {
                // The project filter's options, loaded once and apart from the chart, so a chart
                // that fails or has not answered leaves the filter as it was. Billing reads them
                // from every report the organization has filed, cached for a day on its side.
                loadTeamIdOptions: async (): Promise<number[]> => {
                    try {
                        const response = await api.get('api/billing/usage/team_options/')
                        return response?.team_id_options ?? []
                    } catch {
                        return []
                    }
                },
            },
        ],
        billingUsageResponse: [
            null as BillingUsageResponse | null,
            {
                loadBillingUsage: async (_: void, breakpoint: BreakPointFunction) => {
                    // Three things load on arrival: afterMount, urlToAction once it has read the
                    // filters out of the URL, and the subscriptions that fire when billing settles
                    // whether this is a hobby plan and whether the person may see usage. The
                    // breakpoint keeps only the last call, so one request goes out and it carries
                    // the filters that ended up in effect.
                    //
                    // Before the try below, deliberately: a breakpoint reports itself by throwing,
                    // and catching that as a failure would show the person an error toast.
                    await breakpoint(1)
                    if (!values.canViewUsageAndSpend || values.isHobby) {
                        return null
                    }
                    actions.setBillingUsageError(null)
                    const { usage_types, breakdowns, interval, top_projects } = values.filters
                    // Selecting every project is not a filter, and sending it as one puts a
                    // few thousand characters of project ids in the query string.
                    const team_ids = values.effectiveTeamIds
                    // Only meaningful with a project breakdown - without one there is no
                    // per-project series to fold, and sending it would just be noise.
                    const breakingDownByTeam = !!breakdowns?.includes('team')
                    const params = {
                        ...(usage_types && usage_types.length > 0 ? { usage_types: JSON.stringify(usage_types) } : {}),
                        ...(team_ids && team_ids.length > 0 ? { team_ids: JSON.stringify(team_ids) } : {}),
                        ...(breakdowns && breakdowns.length > 0 ? { breakdowns: JSON.stringify(breakdowns) } : {}),
                        start_date: values.dateFrom,
                        end_date: values.dateTo || DEFAULT_BILLING_USAGE_DATE_TO,
                        ...(interval ? { interval } : {}),
                        ...(breakingDownByTeam && top_projects ? { top_projects } : {}),
                    }
                    try {
                        // One request whatever the breakdown. Billing ranks and folds the projects
                        // itself when there is a cap, and reads every project on every key in one
                        // pass when there is not, so nothing is asked per usage type or per page.
                        // Past what it can hold it refuses with guidance, which the catch below shows.
                        return await api.get(`api/billing/usage/?${toParams(params)}`)
                    } catch (error) {
                        const billingUsageError = getBillingUsageError(error)
                        const isActionable =
                            !!billingUsageError && ACTIONABLE_BILLING_ERROR_CODES.includes(billingUsageError.code)
                        actions.setBillingUsageError(isActionable ? billingUsageError : null)
                        if (!isActionable) {
                            lemonToast.error('Failed to load billing usage. Please try again or contact support.')
                            throw error
                        }
                        return null
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
        // Null means the range has no end yet: "This year" and its kind carry only a start, and
        // the picker recognises its own preset only while the end stays empty. With the end filled
        // in, every such preset would read back as "No date range override". The request supplies
        // the end when it is sent.
        dateTo: [
            (props.dateTo || DEFAULT_BILLING_USAGE_DATE_TO) as string | null,
            {
                setDateRange: (_, { dateTo }) => dateTo,
                resetFilters: () => props.dateTo || DEFAULT_BILLING_USAGE_DATE_TO,
            },
        ],
        userHiddenSeries: [
            [] as number[],
            {
                toggleSeries: (state: number[], { id }: { id: number }) =>
                    state.includes(id) ? state.filter((i: number) => i !== id) : [...state, id],
                setHiddenSeries: (_: number[], { ids }: { ids: number[] }) => ids,
            },
        ],
        // null means "whatever the default is for this view", so the default can change with
        // the breakdown without overwriting a choice the person made.
        chartType: [
            null as BillingChartType | null,
            {
                setChartType: (_, { chartType }: { chartType: BillingChartType | null }) => chartType,
            },
        ],
        excludeEmptySeries: [
            false,
            {
                setExcludeEmptySeries: (_, { exclude }: { exclude: boolean }) => exclude,
                resetFilters: () => false,
            },
        ],
        billingUsageError: [
            null as BillingUsageError | null,
            {
                setBillingUsageError: (_, { error }) => error,
            },
        ],
    })),
    selectors({
        usageExportUrl: [
            (s) => [s.filters, s.dateFrom, s.dateTo, s.effectiveTeamIds],
            (
                filters: BillingFilters,
                dateFrom: string,
                dateTo: string | null,
                effectiveTeamIds: number[] | undefined
            ): string =>
                // Every project in the period: the page's filters without the chart's project cap,
                // which is how the chart is drawn and not part of the data.
                usageExportUrlFor(filters, dateFrom, dateTo, effectiveTeamIds, false),
        ],
        usageChartExportUrl: [
            (s) => [s.filters, s.dateFrom, s.dateTo, s.effectiveTeamIds],
            (
                filters: BillingFilters,
                dateFrom: string,
                dateTo: string | null,
                effectiveTeamIds: number[] | undefined
            ): string =>
                // The chart's series as billing built them, cap and folded row included.
                usageExportUrlFor(filters, dateFrom, dateTo, effectiveTeamIds, true),
        ],
        dateOptions: [
            (s) => [s.billingPeriodUTC],
            (currentPeriod: import('~/types').BillingPeriod): DateMappingOption[] => {
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
                const dayAndMonthOptions = dateMapping.filter(isDayOrCoarser).filter(fitsOneRequest)
                return [currentBillingPeriodOption, previousBillingPeriodOption, ...dayAndMonthOptions]
            },
        ],
        billingPeriodMarkers: [
            (s) => [s.billingPeriodUTC, s.dateFrom, s.dateTo],
            (
                currentPeriod: import('~/types').BillingPeriod,
                dateFrom: string,
                dateTo: string | null
            ): BillingPeriodMarker[] => {
                return calculateBillingPeriodMarkers(currentPeriod, dateFrom, dateTo)
            },
        ],
        series: [
            (s) => [s.billingUsageResponse],
            (response: BillingUsageResponse | null) => {
                if (!response?.results) {
                    return []
                }

                return response.results.map(convertDesktopUsageSeries)
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
        canStackSeries: [
            (s) => [s.filters],
            // Usage series always carry a usage type, and the types have different units:
            // events, recordings, megabytes. Stacking them gives a total with no unit.
            // Narrowing to a single type makes every series the same thing, and then it does.
            (filters: BillingFilters): boolean => filters.usage_types?.length === 1,
        ],
        defaultChartType: [
            () => [],
            // Usage is a set of unrelated quantities more often than not, so the default is a
            // line; stacking becomes available once the series share a unit.
            (): BillingChartType => 'line',
        ],
        effectiveChartType: [
            (s) => [s.chartType, s.defaultChartType, s.canStackSeries],
            // A URL can name a chart type the data cannot support, so the guard is here as
            // well as on the control.
            (
                chartType: BillingChartType | null,
                defaultChartType: BillingChartType,
                canStackSeries: boolean
            ): BillingChartType => {
                const wanted = chartType ?? defaultChartType
                return wanted === 'bar' && !canStackSeries ? 'line' : wanted
            },
        ],
        finalHiddenSeries: [
            (s) => [s.userHiddenSeries, s.excludeEmptySeries, s.emptySeriesIDs],
            (userHiddenSeries: number[], excludeEmptySeries: boolean, emptySeriesIDs: number[]) =>
                excludeEmptySeries ? Array.from(new Set([...userHiddenSeries, ...emptySeriesIDs])) : userHiddenSeries,
        ],
        showSeries: [
            (s) => [s.billingUsageResponseLoading, s.series, s.billingUsageError],
            (
                billingUsageResponseLoading: boolean,
                series: billingUsageLogicType['values']['series'],
                billingUsageError: BillingUsageError | null
            ) => billingUsageResponseLoading || (!billingUsageError && series.length > 0),
        ],
        showEmptyState: [
            (s) => [s.showSeries, s.billingUsageResponse, s.billingUsageError],
            (
                showSeries: boolean,
                billingUsageResponse: BillingUsageResponse | null,
                billingUsageError: BillingUsageError | null
            ) => !showSeries && !!billingUsageResponse && !billingUsageError,
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
            (dateTo: string | null): string | null => {
                if (!dateTo || !dayjs(dateTo).isBefore(dayjs(), 'day')) {
                    return 'Usage is reported on a daily basis so the figures for the current day (UTC) are not available.'
                }
                return null
            },
        ],
        effectiveTeamIds: [
            (s) => [s.filters, s.teamOptions],
            (filters: BillingFilters, teamOptions: { key: string }[]): number[] | undefined =>
                selectionCoversEveryProject(filters.team_ids, teamOptions) ? undefined : filters.team_ids,
        ],
        teamOptions: [
            (s) => [s.currentOrganization, s.teamIdOptions],
            (currentOrganization: OrganizationType | null, teamIdOptions: number[]) => {
                const liveTeams = currentOrganization?.teams || []
                const liveTeamIds = liveTeams.map((team) => team.id)
                const liveOptions = sortBy(
                    liveTeams.map((team) => ({ key: String(team.id), label: team.name })),
                    'label'
                )

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
                    values.effectiveTeamIds,
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
                    values.dateTo ?? DEFAULT_BILLING_USAGE_DATE_TO,
                    dayjs().subtract(1, 'day').format('YYYY-MM-DD')
                )
                updateBillingSearchParams(
                    params,
                    'top_projects',
                    values.filters.top_projects,
                    DEFAULT_BILLING_USAGE_FILTERS.top_projects
                )
                updateBillingSearchParams(params, 'exclude_empty', values.excludeEmptySeries, false)
                updateBillingSearchParams(params, 'chart', values.chartType, null)
                return params
            })
        }

        return {
            setFilters: () => buildURL(),
            setDateRange: () => buildURL(),
            setChartType: () => buildURL(),
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
            if (params.top_projects !== undefined) {
                // An explicit empty value in the URL means "all projects", which is a real
                // choice and distinct from the parameter being absent.
                const topProjectsFromUrl =
                    params.top_projects === '' || params.top_projects === null ? null : Number(params.top_projects)
                if (topProjectsFromUrl !== values.filters.top_projects && !Number.isNaN(topProjectsFromUrl)) {
                    filtersFromUrl.top_projects = topProjectsFromUrl
                }
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

            if (params.chart !== undefined && params.chart !== values.chartType) {
                actions.setChartType(params.chart === 'bar' ? 'bar' : 'line', false)
            }

            if (params.exclude_empty !== undefined && params.exclude_empty !== values.excludeEmptySeries) {
                actions.setExcludeEmptySeries(Boolean(params.exclude_empty), false)
            }
        }

        // Scoped to this section rather than '*'. The usage and spend pages write the same
        // query parameter names - usage_types, breakdowns, date_from, top_projects, chart - so on
        // '*' each logic would read the other page's filter changes as its own and refetch.
        return {
            [urls.organizationBillingSection('usage')]: urlToAction,
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
            const hidden = new Set(userHiddenSeries)
            const isAllVisible = ids.length > 0 && ids.every((id) => !hidden.has(id))
            actions.reportBillingUsageInteraction(buildTrackingProperties('series_toggled', values))

            // One action for every series. A dispatch per series would re-run every reducer and
            // re-render the whole table once per series.
            actions.setHiddenSeries(isAllVisible ? Array.from(new Set([...userHiddenSeries, ...ids])) : [])
        },
        toggleTeamBreakdown: async (_payload, breakpoint) => {
            await breakpoint(200)
            actions.reportBillingUsageInteraction(buildTrackingProperties('breakdown_toggled', values))
            actions.loadBillingUsage()
        },
    })),
    subscriptions(({ actions, values }) => ({
        canViewUsageAndSpend: (canViewUsageAndSpend: boolean, previousCanViewUsageAndSpend: boolean | undefined) => {
            if (canViewUsageAndSpend && previousCanViewUsageAndSpend === false && !values.isHobby) {
                actions.loadBillingUsage()
            }
        },
        isHobby: (isHobby: boolean, previousIsHobby: boolean | undefined) => {
            if (!isHobby && previousIsHobby === true && values.canViewUsageAndSpend) {
                actions.loadBillingUsage()
            }
        },
    })),
    afterMount(({ actions }: billingUsageLogicType) => {
        actions.loadTeamIdOptions()
        actions.loadBillingUsage()
    }),
])
