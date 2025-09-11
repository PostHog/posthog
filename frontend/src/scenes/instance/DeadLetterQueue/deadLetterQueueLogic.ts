import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { AppMetricsV2RequestParams, SystemStatusRow } from './../../../types'
import type { deadLetterQueueLogicType } from './deadLetterQueueLogicType'

export type TabName = 'overview' | 'internal_metrics'

export enum DeadLetterQueueTab {
    Metrics = 'metrics',
    Management = 'management',
    Settings = 'settings',
}

export interface DeadLetterQueueMetricRow extends SystemStatusRow {
    key: string
}

export type MetricsFilters = Pick<AppMetricsV2RequestParams, 'before' | 'after' | 'interval'>

const DEFAULT_FILTERS: MetricsFilters = {
    before: undefined,
    after: '-7d',
    interval: 'day',
}

export const deadLetterQueueLogic = kea<deadLetterQueueLogicType>([
    path(['scenes', 'instance', 'DeadLetterQueue', 'deadLetterQueueLogic']),

    actions({
        setActiveTab: (tabKey: DeadLetterQueueTab) => ({ tabKey }),
        loadMoreRows: (key: string) => ({ key }),
        addRowsToMetric: (key: string, rows: string[][][]) => ({ key, rows }),
        setFilters: (filters: Partial<MetricsFilters>) => ({ filters }),
    }),

    reducers({
        activeTab: [
            DeadLetterQueueTab.Metrics as DeadLetterQueueTab,
            {
                setActiveTab: (_, { tabKey }) => tabKey,
            },
        ],
        rowsPerMetric: [
            {} as Record<string, string[][][]>,
            {
                addRowsToMetric: (state: Record<string, string[][][]>, { key, rows }) => {
                    return { ...state, [key]: [...(state[key] || []), ...rows] }
                },
                loadDeadLetterQueueMetricsSuccess: (_, { deadLetterQueueMetrics }) => {
                    const rowsPerMetric = {}
                    for (const metric of deadLetterQueueMetrics) {
                        if (metric.subrows) {
                            rowsPerMetric[metric.key] = metric.subrows.rows
                        }
                    }
                    return rowsPerMetric
                },
            },
        ],
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),

    loaders(({ values }) => ({
        deadLetterQueueMetrics: [
            [] as DeadLetterQueueMetricRow[],
            {
                loadDeadLetterQueueMetrics: async () => {
                    if (!userLogic.values.user?.is_staff) {
                        return []
                    }
                    let params: Record<string, string> = {}
                    if (values.filters.before) {
                        params.before = values.filters.before
                    }
                    if (values.filters.after) {
                        params.after = values.filters.after
                    }
                    return (await api.get(`api/dead_letter_queue?${new URLSearchParams(params).toString()}`)).results
                },
            },
        ],
    })),

    listeners(({ values, actions }) => ({
        loadMoreRows: async ({ key }) => {
            const offset = values.rowsPerMetric[key]?.length + 1
            if (offset || values.filters.before || values.filters.after) {
                let params: Record<string, string> = {}
                if (offset) {
                    params.offset = offset.toString()
                }
                if (values.filters.before) {
                    params.before = values.filters.before
                }
                if (values.filters.after) {
                    params.after = values.filters.after
                }
                const res = await api.get(`api/dead_letter_queue/${key}?${new URLSearchParams(params).toString()}`)
                actions.addRowsToMetric(key, res.subrows.rows)
            }
        },
        setFilters: async (_, breakpoint) => {
            await breakpoint(100)
            actions.loadDeadLetterQueueMetrics()
        },
    })),

    selectors({
        singleValueMetrics: [
            (s) => [s.deadLetterQueueMetrics],
            (deadLetterQueueMetrics: DeadLetterQueueMetricRow[]) =>
                deadLetterQueueMetrics.filter((metric) => !metric.subrows),
        ],
        tableMetrics: [
            (s) => [s.deadLetterQueueMetrics],
            (deadLetterQueueMetrics: DeadLetterQueueMetricRow[]) =>
                deadLetterQueueMetrics.filter((metric) => !!metric.subrows),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadDeadLetterQueueMetrics()
    }),
])
