import { connect, events, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { SharedMetric } from './sharedMetricLogic'
import type { sharedMetricsLogicType } from './sharedMetricsLogicType'

export const sharedMetricsLogic = kea<sharedMetricsLogicType>([
    path(['scenes', 'experiments', 'sharedMetricsLogic']),
    connect(() => ({ values: [teamLogic, ['currentProjectId']] })),

    loaders(({ values }) => ({
        sharedMetrics: [
            [] as SharedMetric[],
            {
                loadSharedMetrics: async () => {
                    const response = await api.get(`api/projects/${values.currentProjectId}/experiment_saved_metrics`)
                    return response.results as SharedMetric[]
                },
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSharedMetrics()
        },
    })),
])
