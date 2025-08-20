import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'

import { DataWarehouseActivityRecord, ExternalDataSource } from '~/types'

import type { externalDataSourcesLogicType } from './externalDataSourcesLogicType'

export const externalDataSourcesLogic = kea<externalDataSourcesLogicType>([
    path(['scenes', 'data-warehouse', 'externalDataSourcesLogic']),
    actions({
        abortAnyRunningQuery: true,
        loadRecentActivity: true,
        loadMoreRecentActivity: true,
        setRecentActivityData: (data: DataWarehouseActivityRecord[], hasMore: boolean) => ({ data, hasMore }),
        setActivityCurrentPage: (page: number) => ({ page }),
        checkAutoLoadMore: true,
    }),
    loaders(({ cache, values, actions }) => ({
        dataWarehouseSources: [
            null as PaginatedResponse<ExternalDataSource> | null,
            {
                loadSources: async (_, breakpoint) => {
                    await breakpoint(300)
                    actions.abortAnyRunningQuery()

                    cache.abortController = new AbortController()
                    const methodOptions: ApiMethodOptions = {
                        signal: cache.abortController.signal,
                    }
                    const res = await api.externalDataSources.list(methodOptions)
                    breakpoint()

                    cache.abortController = null

                    return res
                },
                updateSource: async (source: ExternalDataSource) => {
                    const updatedSource = await api.externalDataSources.update(source.id, source)
                    return {
                        ...values.dataWarehouseSources,
                        results:
                            values.dataWarehouseSources?.results.map((s: ExternalDataSource) =>
                                s.id === updatedSource.id ? updatedSource : s
                            ) || [],
                    }
                },
            },
        ],
    })),
    reducers(({ cache }) => ({
        dataWarehouseSourcesLoading: [
            false as boolean,
            {
                loadSources: () => true,
                loadSourcesFailure: () => cache.abortController !== null,
                loadSourcesSuccess: () => cache.abortController !== null,
            },
        ],
        recentActivityHasMore: [
            true as boolean,
            {
                setRecentActivityData: (_, { hasMore }) => hasMore,
                loadRecentActivity: () => true,
            },
        ],
        activityCurrentPage: [
            1 as number,
            {
                setActivityCurrentPage: (_, { page }) => page,
                loadRecentActivity: () => 1, // Reset to first page when loading fresh data
            },
        ],
        recentActivity: [
            [] as DataWarehouseActivityRecord[],
            {
                setRecentActivityData: (_, { data }) => data,
            },
        ],
        recentActivityLoading: [
            false as boolean,
            {
                loadRecentActivity: () => true,
                setRecentActivityData: () => false,
                loadMoreRecentActivity: () => true,
            },
        ],
    })),
    selectors(() => ({
        activityPaginationState: [
            (s) => [s.recentActivity, s.activityCurrentPage],
            (recentActivity: DataWarehouseActivityRecord[], activityCurrentPage: number) => {
                const pageSize = 5
                const totalData = recentActivity.length
                const pageCount = Math.ceil(totalData / pageSize)
                const startIndex = (activityCurrentPage - 1) * pageSize
                const endIndex = Math.min(startIndex + pageSize, totalData)
                const dataSourcePage = recentActivity.slice(startIndex, endIndex)

                return {
                    currentPage: activityCurrentPage,
                    pageCount,
                    dataSourcePage,
                    currentStartIndex: startIndex,
                    currentEndIndex: endIndex,
                    entryCount: totalData,
                    isOnLastPage: activityCurrentPage === pageCount,
                    hasDataOnCurrentPage: dataSourcePage.length > 0,
                }
            },
        ],
    })),
    listeners(({ cache, values, actions }) => ({
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
        setActivityCurrentPage: () => {
            // Trigger auto-load check when page changes
            actions.checkAutoLoadMore()
        },
        checkAutoLoadMore: () => {
            const paginationState = values.activityPaginationState
            const { isOnLastPage, hasDataOnCurrentPage } = paginationState
            const { recentActivityHasMore, recentActivityLoading } = values

            // Auto-load more activities when user reaches the last page and there's more data available
            if (isOnLastPage && hasDataOnCurrentPage && recentActivityHasMore && !recentActivityLoading) {
                actions.loadMoreRecentActivity()
            }
        },
        loadRecentActivitySuccess: () => {
            // Check if we need to auto-load more after loading data
            actions.checkAutoLoadMore()
        },
        loadMoreRecentActivitySuccess: () => {
            // Check if we need to auto-load more after loading more data
            actions.checkAutoLoadMore()
        },
        loadRecentActivity: async () => {
            try {
                const response = await api.dataWarehouse.recentActivity({ limit: 20, offset: 0 })
                actions.setRecentActivityData(response.results || [], !!response.next)
            } catch (error) {
                posthog.captureException(error)
            }
        },
        loadMoreRecentActivity: async () => {
            try {
                const currentData = values.recentActivity
                const response = await api.dataWarehouse.recentActivity({
                    limit: 20,
                    offset: currentData.length,
                })
                const newData = [...currentData, ...(response.results || [])]
                actions.setRecentActivityData(newData, !!response.next)
            } catch (error) {
                posthog.captureException(error)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSources(null)
        actions.loadRecentActivity()
    }),
])
