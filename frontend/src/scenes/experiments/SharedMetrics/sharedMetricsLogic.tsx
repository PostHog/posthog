import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { PaginationManual } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { toParams } from 'lib/utils'

import type { SharedMetric } from './sharedMetricLogic'
import type { sharedMetricsLogicType } from './sharedMetricsLogicType'

export const SHARED_METRICS_PER_PAGE = 30

export interface SharedMetricsFilters {
    search?: string
    page?: number
}

const DEFAULT_FILTERS: SharedMetricsFilters = {
    search: undefined,
    page: 1,
}

export interface SharedMetricsResult extends CountedPaginatedResponse<SharedMetric> {}

export const sharedMetricsLogic = kea<sharedMetricsLogicType>([
    path(['scenes', 'experiments', 'sharedMetricsLogic']),
    connect(() => ({
        values: [router, ['location']],
    })),
    actions({
        setSharedMetricsFilters: (filters: Partial<SharedMetricsFilters>, replace?: boolean) => ({ filters, replace }),
    }),
    loaders(({ values }) => ({
        sharedMetrics: {
            __default: { results: [], count: 0 } as SharedMetricsResult,
            loadSharedMetrics: async () => {
                const response = await api.get(
                    `api/projects/@current/experiment_saved_metrics?${toParams(values.paramsFromFilters)}`
                )
                return {
                    results: response.results as SharedMetric[],
                    count: response.count || response.results.length,
                }
            },
        },
    })),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setSharedMetricsFilters: (state, { filters, replace }) => {
                    if (replace) {
                        return { ...filters }
                    }
                    return { ...state, ...filters }
                },
            },
        ],
    }),
    selectors(({ actions }) => ({
        paramsFromFilters: [
            (s) => [s.filters],
            (filters: SharedMetricsFilters) => ({
                ...(filters.search ? { search: filters.search } : {}),
                limit: SHARED_METRICS_PER_PAGE,
                offset: filters.page ? (filters.page - 1) * SHARED_METRICS_PER_PAGE : 0,
            }),
        ],
        count: [(s) => [s.sharedMetrics], (sharedMetrics) => sharedMetrics.count],
        pagination: [
            (s) => [s.filters, s.count],
            (filters, count): PaginationManual => {
                const currentPage = filters.page || 1
                const hasNextPage = count > currentPage * SHARED_METRICS_PER_PAGE
                const hasPreviousPage = currentPage > 1

                return {
                    controlled: true,
                    pageSize: SHARED_METRICS_PER_PAGE,
                    currentPage,
                    entryCount: count,
                    onForward: hasNextPage
                        ? () => actions.setSharedMetricsFilters({ page: currentPage + 1 })
                        : undefined,
                    onBackward: hasPreviousPage
                        ? () => actions.setSharedMetricsFilters({ page: Math.max(1, currentPage - 1) })
                        : undefined,
                }
            },
        ],
    })),
    listeners(({ actions }) => ({
        setSharedMetricsFilters: async (_, breakpoint) => {
            await breakpoint(300) // Debounce search
            actions.loadSharedMetrics()
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSharedMetrics()
        },
    })),
])
