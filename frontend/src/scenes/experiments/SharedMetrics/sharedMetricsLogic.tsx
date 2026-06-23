import { actions, connect, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { toParams } from 'lib/utils/url'
import { teamLogic } from 'scenes/teamLogic'

import type { SharedMetric } from './sharedMetricLogic'
import type { sharedMetricsLogicType } from './sharedMetricsLogicType'

export const PAGE_SIZE = 100

export const sharedMetricsLogic = kea<sharedMetricsLogicType>([
    path(['scenes', 'experiments', 'sharedMetricsLogic']),
    connect(() => ({ values: [teamLogic, ['currentProjectId']] })),

    actions({
        updateSharedMetricTags: (metricId: SharedMetric['id'], tags: string[]) => ({ metricId, tags }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setPage: (page: number) => ({ page }),
        setCount: (count: number) => ({ count }),
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
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setSearchTerm: () => 1,
            },
        ],
        count: [
            0,
            {
                setCount: (_, { count }) => count,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        sharedMetrics: [
            [] as SharedMetric[],
            {
                loadSharedMetrics: async (_: void, breakpoint) => {
                    const params = toParams({
                        limit: PAGE_SIZE,
                        offset: (values.page - 1) * PAGE_SIZE,
                        search: values.searchTerm || undefined,
                    })
                    const response: CountedPaginatedResponse<SharedMetric> = await api.get(
                        `api/projects/${values.currentProjectId}/experiment_saved_metrics?${params}`
                    )
                    // Discard stale responses that resolve after a newer search has fired
                    breakpoint()
                    actions.setCount(response.count)
                    return response.results
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        setPage: async () => {
            actions.loadSharedMetrics()
        },
        setSearchTerm: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadSharedMetrics()
        },
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
