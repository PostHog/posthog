import { SystemStatusRow } from './../../../types'
import api from 'lib/api'
import { kea } from 'kea'
import { userLogic } from 'scenes/userLogic'

import { deadLetterQueueLogicType } from './deadLetterQueueLogicType'
export type TabName = 'overview' | 'internal_metrics'

export const deadLetterQueueLogic = kea<deadLetterQueueLogicType>({
    path: ['scenes', 'instance', 'DeadLetterQueue', 'deadLetterQueueLogic'],

    actions: () => ({
        setActiveTab: (tabKey: string) => ({ tabKey }),
    }),

    reducers: () => ({
        activeTab: [
            'dlq_size',
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
        currentMetric: [
            (s) => [s.activeTab, s.deadLetterQueueMetrics],
            (activeTab, deadLetterQueueMetrics) => deadLetterQueueMetrics.filter((row) => row.key === activeTab)[0],
        ],
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadDeadLetterQueueMetrics()
        },
    }),
})
