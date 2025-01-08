import { actions, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'

import { SavedMetric } from './savedMetricLogic'
import type { savedMetricsLogicType } from './savedMetricsLogicType'

export enum SavedMetricsTabs {
    All = 'all',
    Yours = 'yours',
    Archived = 'archived',
}

export const savedMetricsLogic = kea<savedMetricsLogicType>([
    path(['scenes', 'experiments', 'savedMetricsLogic']),
    actions({
        setSavedMetricsTab: (tabKey: SavedMetricsTabs) => ({ tabKey }),
    }),

    loaders({
        savedMetrics: {
            loadSavedMetrics: async () => {
                const response = await api.get('api/projects/@current/experiment_saved_metrics')
                return response.results as SavedMetric[]
            },
        },
    }),

    reducers({
        tab: [
            SavedMetricsTabs.All as SavedMetricsTabs,
            {
                setSavedMetricsTab: (_, { tabKey }) => tabKey,
            },
        ],
    }),
    listeners(() => ({
        setSavedMetricsTab: () => {
            router.actions.push('/experiments/shared-metrics')
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSavedMetrics()
        },
    })),
])
