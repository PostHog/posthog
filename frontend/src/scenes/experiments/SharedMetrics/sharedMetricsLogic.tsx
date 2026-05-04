import { actions, connect, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { SharedMetric } from './sharedMetricLogic'
import type { sharedMetricsLogicType } from './sharedMetricsLogicType'

export const sharedMetricsLogic = kea<sharedMetricsLogicType>([
    path(['scenes', 'experiments', 'sharedMetricsLogic']),
    connect(() => ({ values: [teamLogic, ['currentProjectId']] })),

    actions({
        updateSharedMetricTags: (metricId: SharedMetric['id'], tags: string[]) => ({ metricId, tags }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        deleteSharedMetric: (metricId: SharedMetric['id']) => ({ metricId }),
    }),

    reducers({
        savingTagsMetricId: [
            null as SharedMetric['id'] | null,
            {
                updateSharedMetricTags: (_, { metricId }) => metricId,
                loadSharedMetricsSuccess: () => null,
                loadSharedMetricsFailure: () => null,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),

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

    listeners(({ actions, values }) => ({
        updateSharedMetricTags: async ({ metricId, tags }) => {
            try {
                await api.update(`api/projects/${values.currentProjectId}/experiment_saved_metrics/${metricId}`, {
                    tags,
                })
                actions.loadSharedMetrics()
            } catch {
                lemonToast.error('Failed to save tags')
                actions.loadSharedMetrics()
            }
        },
        deleteSharedMetric: async ({ metricId }) => {
            try {
                await api.delete(`api/projects/${values.currentProjectId}/experiment_saved_metrics/${metricId}`)
                lemonToast.success('Shared metric deleted successfully')
                actions.loadSharedMetrics()
            } catch {
                lemonToast.error('Failed to delete shared metric')
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSharedMetrics()
        },
    })),
])
