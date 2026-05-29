import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { toParams } from 'lib/utils'
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
                loadSharedMetrics: async () => {
                    const params = toParams({
                        limit: PAGE_SIZE,
                        offset: (values.page - 1) * PAGE_SIZE,
                        search: values.searchTerm || undefined,
                    })
                    const response: CountedPaginatedResponse<SharedMetric> = await api.get(
                        `api/projects/${values.currentProjectId}/experiment_saved_metrics?${params}`
                    )
                    actions.setCount(response.count)
                    return response.results
                },
            },
        ],
    })),

    selectors(({ actions }) => ({
        pagination: [
            (s) => [s.page, s.count],
            (page, count): PaginationManual => ({
                controlled: true,
                pageSize: PAGE_SIZE,
                currentPage: page,
                entryCount: count,
                onForward: () => actions.setPage(page + 1),
                onBackward: () => actions.setPage(page - 1),
            }),
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

    actionToUrl(({ values }) => {
        const buildUrl = (): [string, Record<string, string>] => {
            const params: Record<string, string> = {}
            if (values.page > 1) {
                params.page = String(values.page)
            }
            if (values.searchTerm) {
                params.search = values.searchTerm
            }
            return ['/experiments/shared-metrics', params]
        }
        return {
            setPage: () => buildUrl(),
            setSearchTerm: () => buildUrl(),
        }
    }),

    urlToAction(({ actions, values }) => ({
        '/experiments/shared-metrics': (_, searchParams) => {
            const urlPage = parseInt(searchParams.page ?? '1') || 1
            const urlSearch = searchParams.search ?? ''
            const searchChanged = urlSearch !== values.searchTerm
            if (searchChanged) {
                // setSearchTerm resets page to 1, so apply it first then restore the URL's page below.
                actions.setSearchTerm(urlSearch)
            }
            // After a search change the page is 1; set the URL page whenever it differs from the resulting page.
            if (urlPage !== (searchChanged ? 1 : values.page)) {
                actions.setPage(urlPage)
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSharedMetrics()
        },
    })),
])
