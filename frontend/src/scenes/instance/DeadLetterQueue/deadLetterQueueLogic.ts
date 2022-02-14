import { SystemStatusRow } from './../../../types'
import api from 'lib/api'
import { kea } from 'kea'
import { userLogic } from 'scenes/userLogic'

import { deadLetterQueueLogicType } from './deadLetterQueueLogicType'
export type TabName = 'overview' | 'internal_metrics'

export enum DeadLetterQueueTab {
    Metrics = 'metrics',
    Management = 'management',
    Settings = 'settings',
}

export interface DeadLetterQueueMetricRow extends SystemStatusRow {
    key: string
}

export const deadLetterQueueLogic = kea<deadLetterQueueLogicType<DeadLetterQueueMetricRow>>({
    path: ['scenes', 'instance', 'DeadLetterQueue', 'deadLetterQueueLogic'],

    actions: () => ({
        setActiveTab: (tabKey: string) => ({ tabKey }),
        loadMoreRows: (key: string) => ({ key }),
        addRowsToMetric: (key: string, rows: any[]) => ({ key, rows }),
        setRowsPerMetricKey: (map: Record<string, any[]>) => ({ map }),
    }),

    reducers: () => ({
        activeTab: [
            DeadLetterQueueTab.Metrics,
            {
                setActiveTab: (_, { tabKey }) => tabKey,
            },
        ],
        rowsPerMetric: [
            {} as Record<string, any[]>,
            {
                addRowsToMetric: (state, { key, rows }) => {
                    return { ...state, [key]: [...(state[key] || []), ...rows] }
                },
                setRowsPerMetricKey: (_, { map }) => map,
            },
        ],
    }),

    loaders: ({ actions }) => ({
        deadLetterQueueMetrics: [
            [] as DeadLetterQueueMetricRow[],
            {
                loadDeadLetterQueueMetrics: async () => {
                    if (!userLogic.values.user?.is_staff) {
                        return []
                    }
                    const metrics = (await api.get('api/dead_letter_queue')).results

                    const rowsPerMetric = {}
                    for (const metric of metrics.filter((m: DeadLetterQueueMetricRow) => !!m.subrows)) {
                        rowsPerMetric[metric.key] = metric.subrows.rows
                    }
                    actions.setRowsPerMetricKey(rowsPerMetric)
                    return metrics
                },
            },
        ],
    }),

    listeners: ({ values, actions }) => ({
        loadMoreRows: async ({ key }) => {
            const offset = values.rowsPerMetric[key]?.length + 1
            if (offset) {
                const res = await api.get(`api/dead_letter_queue/${key}?offset=${offset}`)
                actions.addRowsToMetric(key, res.subrows.rows)
            }
        },
    }),

    selectors: () => ({
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

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadDeadLetterQueueMetrics()
        },
    }),
})
