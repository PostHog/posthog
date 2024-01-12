import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { SystemStatusRow } from './../../../types'
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

export const deadLetterQueueLogic = kea<deadLetterQueueLogicType>([
    path(['scenes', 'instance', 'DeadLetterQueue', 'deadLetterQueueLogic']),

    actions({
        setActiveTab: (tabKey: DeadLetterQueueTab) => ({ tabKey }),
        loadMoreRows: (key: string) => ({ key }),
        addRowsToMetric: (key: string, rows: string[][][]) => ({ key, rows }),
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
    }),

    loaders({
        deadLetterQueueMetrics: [
            [] as DeadLetterQueueMetricRow[],
            {
                loadDeadLetterQueueMetrics: async () => {
                    if (!userLogic.values.user?.is_staff) {
                        return []
                    }
                    return (await api.get('api/dead_letter_queue')).results
                },
            },
        ],
    }),

    listeners(({ values, actions }) => ({
        loadMoreRows: async ({ key }) => {
            const offset = values.rowsPerMetric[key]?.length + 1
            if (offset) {
                const res = await api.get(`api/dead_letter_queue/${key}?offset=${offset}`)
                actions.addRowsToMetric(key, res.subrows.rows)
            }
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
