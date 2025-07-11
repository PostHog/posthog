import { actions, connect, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'

import type { SharedMetric } from './sharedMetricLogic'
import type { sharedMetricsLogicType } from './sharedMetricsLogicType'

export enum SharedMetricsTabs {
    All = 'all',
    Yours = 'yours',
    Archived = 'archived',
}

export const sharedMetricsLogic = kea<sharedMetricsLogicType>([
    path(['scenes', 'experiments', 'sharedMetricsLogic']),
    connect(() => ({})),
    actions({
        setSharedMetricsTab: (tabKey: SharedMetricsTabs) => ({ tabKey }),
    }),

    loaders({
        sharedMetrics: [
            [] as SharedMetric[],
            {
                loadSharedMetrics: async () => {
                    const response = await api.get('api/projects/@current/experiment_saved_metrics')
                    return response.results as SharedMetric[]
                },
            },
        ],
    }),

    reducers({
        tab: [
            SharedMetricsTabs.All as SharedMetricsTabs,
            {
                setSharedMetricsTab: (_, { tabKey }) => tabKey,
            },
        ],
    }),
    listeners(() => ({
        setSharedMetricsTab: () => {
            router.actions.push('/experiments/shared-metrics')
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSharedMetrics()
        },
    })),
])
