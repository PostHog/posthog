import { connect, events, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { SharedMetric } from './sharedMetricLogic'
import type { sharedMetricsLogicType } from './sharedMetricsLogicType'

export const sharedMetricsLogic = kea<sharedMetricsLogicType>([
    path(['scenes', 'experiments', 'sharedMetricsLogic']),
    connect(() => ({})),

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
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSharedMetrics()
        },
    })),
])
