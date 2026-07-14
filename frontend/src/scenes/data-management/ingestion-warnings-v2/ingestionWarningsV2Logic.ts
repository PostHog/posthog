import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { range } from 'lib/utils/arrays'
import { toParams } from 'lib/utils/url'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { teamLogic } from '../../teamLogic'
import type { ingestionWarningsV2LogicType } from './ingestionWarningsV2LogicType'

// No generated types for this endpoint yet: it is attributed to `data_management`,
// which has no products/ frontend module, so these mirror IngestionWarningsV2SummarySerializer.
export interface IngestionWarningV2Sample {
    timestamp: string
    source: string
    pipeline_step: string
    event_uuid: string | null
    distinct_id: string | null
    person_id: string | null
    group_key: string | null
    details: Record<string, any>
}

export interface IngestionWarningV2SparklinePoint {
    timestamp: string
    count: number
}

export interface IngestionWarningV2Summary {
    type: string
    category: string
    severity: string
    count: number
    last_seen: string
    sparkline: IngestionWarningV2SparklinePoint[]
    samples: IngestionWarningV2Sample[]
}

export type IngestionWarningsTimeWindow = '24h' | '7d' | '30d'
export type IngestionWarningsOrderBy = 'count' | 'last_seen'

export interface IngestionWarningsFilters {
    q: string
    window: IngestionWarningsTimeWindow
    category: string | null
    severity: string | null
    orderBy: IngestionWarningsOrderBy
}

export interface IngestionWarningsSummaryStats {
    totalCount: number
    bySeverity: Record<string, number>
}

const DEFAULT_FILTERS: IngestionWarningsFilters = {
    q: '',
    window: '30d',
    category: null,
    severity: null,
    orderBy: 'count',
}

const TIME_WINDOWS: IngestionWarningsTimeWindow[] = ['24h', '7d', '30d']

// One extra slot so the partial bucket at the window's far edge still has a home.
const TIME_WINDOW_CONFIG: Record<IngestionWarningsTimeWindow, { slots: number; unit: 'hour' | 'day' }> = {
    '24h': { slots: 25, unit: 'hour' },
    '7d': { slots: 8, unit: 'day' },
    '30d': { slots: 31, unit: 'day' },
}

const SAMPLES_PER_TYPE = 50

function filtersFromParams(searchParams: Record<string, any>): IngestionWarningsFilters {
    return {
        q: typeof searchParams.q === 'string' ? searchParams.q : '',
        window: TIME_WINDOWS.includes(searchParams.window) ? searchParams.window : DEFAULT_FILTERS.window,
        category: searchParams.category || null,
        severity: searchParams.severity || null,
        orderBy: searchParams.order_by === 'last_seen' ? 'last_seen' : DEFAULT_FILTERS.orderBy,
    }
}

function paramsFromFilters(filters: IngestionWarningsFilters): Record<string, any> {
    const searchParams: Record<string, any> = {}
    if (filters.q) {
        searchParams.q = filters.q
    }
    if (filters.window !== DEFAULT_FILTERS.window) {
        searchParams.window = filters.window
    }
    if (filters.category) {
        searchParams.category = filters.category
    }
    if (filters.severity) {
        searchParams.severity = filters.severity
    }
    if (filters.orderBy !== DEFAULT_FILTERS.orderBy) {
        searchParams.order_by = filters.orderBy
    }
    return searchParams
}

export const ingestionWarningsV2Logic = kea<ingestionWarningsV2LogicType>([
    path(['scenes', 'data-management', 'ingestion-warnings-v2', 'ingestionWarningsV2Logic']),

    connect(() => ({
        values: [teamLogic, ['timezone'], projectLogic, ['currentProjectId']],
    })),

    actions({
        setFilters: (filters: Partial<IngestionWarningsFilters>) => ({ filters }),
    }),

    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),

    loaders(({ values }) => ({
        warnings: [
            [] as IngestionWarningV2Summary[],
            {
                loadWarnings: async (_: void, breakpoint) => {
                    await breakpoint(150)
                    const { q, window, category, severity, orderBy } = values.filters
                    const params = toParams({
                        since: `-${window}`,
                        samples: SAMPLES_PER_TYPE,
                        order_by: orderBy,
                        ...(q ? { q } : {}),
                        ...(category ? { category } : {}),
                        ...(severity ? { severity } : {}),
                    })
                    const response = await api.get(
                        `api/projects/${values.currentProjectId}/ingestion_warnings_v2/?${params}`
                    )
                    breakpoint()
                    return response
                },
            },
        ],
    })),

    selectors({
        bucketLabels: [
            (s) => [s.filters],
            (filters: IngestionWarningsFilters): string[] => {
                const { slots, unit } = TIME_WINDOW_CONFIG[filters.window]
                return range(0, slots)
                    .map((i) =>
                        dayjs()
                            .subtract(i, unit)
                            .format(unit === 'hour' ? 'D MMM HH:00' : 'D MMM YYYY')
                    )
                    .reverse()
            },
        ],
        summaryDatasets: [
            (s) => [s.warnings, s.filters, s.timezone],
            (
                warnings: IngestionWarningV2Summary[],
                filters: IngestionWarningsFilters,
                timezone: string
            ): Record<string, number[]> => {
                const { slots, unit } = TIME_WINDOW_CONFIG[filters.window]
                const summaryDatasets: Record<string, number[]> = {}
                warnings.forEach((summary) => {
                    const result = Array.from({ length: slots }, () => 0)
                    for (const point of summary.sparkline) {
                        const bucket = dayjsUtcToTimezone(point.timestamp, timezone)
                        const index = dayjs().diff(bucket, unit)
                        if (index >= 0 && index < slots) {
                            result[index] = point.count
                        }
                    }
                    summaryDatasets[summary.type] = result.reverse()
                })
                return summaryDatasets
            },
        ],
        summaryStats: [
            (s) => [s.warnings],
            (warnings: IngestionWarningV2Summary[]): IngestionWarningsSummaryStats => {
                const bySeverity: Record<string, number> = {}
                let totalCount = 0
                for (const summary of warnings) {
                    totalCount += summary.count
                    bySeverity[summary.severity] = (bySeverity[summary.severity] || 0) + summary.count
                }
                return { totalCount, bySeverity }
            },
        ],
        hasActiveFilters: [
            (s) => [s.filters],
            (filters: IngestionWarningsFilters): boolean => !!filters.category || !!filters.severity || !!filters.q,
        ],
        showProductIntro: [
            (s) => [s.warnings, s.warningsLoading, s.hasActiveFilters],
            (warnings: IngestionWarningV2Summary[], warningsLoading: boolean, hasActiveFilters: boolean): boolean =>
                warnings.length === 0 && !warningsLoading && !hasActiveFilters,
        ],
    }),

    listeners(({ actions }) => ({
        setFilters: () => {
            actions.loadWarnings()
        },
    })),

    actionToUrl(({ values }) => ({
        setFilters: () => [
            router.values.location.pathname,
            paramsFromFilters(values.filters),
            router.values.hashParams,
            { replace: true },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.ingestionWarningsV2()]: (_, searchParams) => {
            const filters = filtersFromParams(searchParams)
            if (JSON.stringify(filters) !== JSON.stringify(values.filters)) {
                actions.setFilters(filters)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.setFilters(filtersFromParams(router.values.searchParams))
    }),
])
