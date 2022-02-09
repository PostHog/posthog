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

export const deadLetterQueueLogic = kea<deadLetterQueueLogicType>({
    path: ['scenes', 'instance', 'DeadLetterQueue', 'deadLetterQueueLogic'],

    actions: () => ({
        setActiveTab: (tabKey: string) => ({ tabKey }),
    }),

    reducers: () => ({
        activeTab: [
            DeadLetterQueueTab.Metrics,
            {
                setActiveTab: (_, { tabKey }) => tabKey,
            },
        ],
    }),

    loaders: () => ({
        deadLetterQueueMetrics: [
            [] as SystemStatusRow[],
            {
                loadDeadLetterQueueMetrics: async () => {
                    if (!userLogic.values.user?.is_staff) {
                        return []
                    }
                    return (await api.get('api/dead_letter_queue')).results?.overview
                },
            },
        ],
    }),

    selectors: () => ({
        singleValueMetrics: [
            (s) => [s.deadLetterQueueMetrics],
            (deadLetterQueueMetrics) => deadLetterQueueMetrics.filter((metric) => !metric.subrows),
        ],
        tableMetrics: [
            (s) => [s.deadLetterQueueMetrics],
            (deadLetterQueueMetrics) => deadLetterQueueMetrics.filter((metric) => !!metric.subrows),
        ],
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadDeadLetterQueueMetrics()
        },
    }),
})
