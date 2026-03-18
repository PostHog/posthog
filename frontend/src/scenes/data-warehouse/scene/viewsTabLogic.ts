import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import {
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryDependencies,
    DataWarehouseSavedQueryRunHistory,
} from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import type { viewsTabLogicType } from './viewsTabLogicType'

export const PAGE_SIZE = 10

export const viewsTabLogic = kea<viewsTabLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'viewsTabLogic']),
    connect(() => ({
        values: [dataWarehouseViewsLogic, ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueriesLoading']],
        actions: [dataWarehouseViewsLogic, ['deleteDataWarehouseSavedQuery', 'runDataWarehouseSavedQuery']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        deleteView: (viewId: string) => ({ viewId }),
        runMaterialization: (viewId: string) => ({ viewId }),
        loadDependenciesForMaterializedViews: (viewIds: string[]) => ({ viewIds }),
        loadDependenciesForViews: (viewIds: string[]) => ({ viewIds }),
        loadRunHistoryForViews: (viewIds: string[]) => ({ viewIds }),
        setMaterializedViewsPage: (page: number) => ({ page }),
        setViewsPage: (page: number) => ({ page }),
        loadVisibleData: true,
    }),
    reducers({
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        materializedViewsCurrentPage: [
            1 as number,
            {
                setMaterializedViewsPage: (_, { page }) => page,
                setSearchTerm: () => 1, // Reset to page 1 on search
            },
        ],
        viewsCurrentPage: [
            1 as number,
            {
                setViewsPage: (_, { page }) => page,
                setSearchTerm: () => 1, // Reset to page 1 on search
            },
        ],
    }),
    loaders(({ values }) => ({
        materializedViewDependenciesMap: [
            {} as Record<string, DataWarehouseSavedQueryDependencies>,
            {
                loadDependenciesForMaterializedViews: async ({ viewIds }) => {
                    // Filter out views we've already loaded
                    const viewsToLoad = viewIds.filter((id) => !values.materializedViewDependenciesMap[id])

                    if (viewsToLoad.length === 0) {
                        return values.materializedViewDependenciesMap
                    }

                    const results = await Promise.all(
                        viewsToLoad.map(async (viewId) => {
                            try {
                                const data = await api.dataWarehouseSavedQueries.dependencies(viewId)
                                return { viewId, data }
                            } catch (error) {
                                console.error(`Failed to load dependencies for view ${viewId}:`, error)
                                return { viewId, data: { upstream_count: 0, downstream_count: 0 } }
                            }
                        })
                    )

                    const newMap = { ...values.materializedViewDependenciesMap }
                    results.forEach(({ viewId, data }) => {
                        newMap[viewId] = data
                    })
                    return newMap
                },
            },
        ],
        viewDependenciesMap: [
            {} as Record<string, DataWarehouseSavedQueryDependencies>,
            {
                loadDependenciesForViews: async ({ viewIds }) => {
                    // Filter out views we've already loaded
                    const viewsToLoad = viewIds.filter((id) => !values.viewDependenciesMap[id])

                    if (viewsToLoad.length === 0) {
                        return values.viewDependenciesMap
                    }

                    const results = await Promise.all(
                        viewsToLoad.map(async (viewId) => {
                            try {
                                const data = await api.dataWarehouseSavedQueries.dependencies(viewId)
                                return { viewId, data }
                            } catch (error) {
                                console.error(`Failed to load dependencies for view ${viewId}:`, error)
                                return { viewId, data: { upstream_count: 0, downstream_count: 0 } }
                            }
                        })
                    )

                    const newMap = { ...values.viewDependenciesMap }
                    results.forEach(({ viewId, data }) => {
                        newMap[viewId] = data
                    })
                    return newMap
                },
            },
        ],
        runHistoryMap: [
            {} as Record<string, DataWarehouseSavedQueryRunHistory[]>,
            {
                loadRunHistoryForViews: async ({ viewIds }) => {
                    // Filter out views we've already loaded
                    const viewsToLoad = viewIds.filter((id) => !values.runHistoryMap[id])

                    if (viewsToLoad.length === 0) {
                        return values.runHistoryMap
                    }

                    const results = await Promise.all(
                        viewsToLoad.map(async (viewId) => {
                            try {
                                const data = await api.dataWarehouseSavedQueries.runHistory(viewId)
                                return { viewId, data: data.run_history }
                            } catch (error) {
                                console.error(`Failed to load run history for view ${viewId}:`, error)
                                return { viewId, data: [] }
                            }
                        })
                    )

                    const newMap = { ...values.runHistoryMap }
                    results.forEach(({ viewId, data }) => {
                        newMap[viewId] = data
                    })
                    return newMap
                },
            },
        ],
    })),
    selectors({
        viewsLoading: [(s) => [s.dataWarehouseSavedQueriesLoading], (loading): boolean => loading],
        enrichedMaterializedViews: [
            (s) => [s.dataWarehouseSavedQueries, s.materializedViewDependenciesMap, s.runHistoryMap],
            (
                queries: DataWarehouseSavedQuery[],
                dependenciesMap: Record<string, DataWarehouseSavedQueryDependencies>,
                runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
            ): DataWarehouseSavedQuery[] => {
                return queries
                    .filter((q) => q.is_materialized)
                    .map((query) => ({
                        ...query,
                        upstream_dependency_count: dependenciesMap[query.id]?.upstream_count,
                        downstream_dependency_count: dependenciesMap[query.id]?.downstream_count,
                        run_history: runHistoryMap[query.id],
                    }))
            },
        ],
        enrichedViews: [
            (s) => [s.dataWarehouseSavedQueries, s.viewDependenciesMap],
            (
                queries: DataWarehouseSavedQuery[],
                dependenciesMap: Record<string, DataWarehouseSavedQueryDependencies>
            ): DataWarehouseSavedQuery[] => {
                return queries
                    .filter((q) => !q.is_materialized)
                    .map((query) => ({
                        ...query,
                        upstream_dependency_count: dependenciesMap[query.id]?.upstream_count,
                        downstream_dependency_count: dependenciesMap[query.id]?.downstream_count,
                    }))
            },
        ],
        filteredViews: [
            (s) => [s.enrichedViews, s.searchTerm],
            (views: DataWarehouseSavedQuery[], searchTerm: string): DataWarehouseSavedQuery[] => {
                if (!searchTerm) {
                    return views
                }
                return views.filter((v) => v.name.toLowerCase().includes(searchTerm.toLowerCase()))
            },
        ],
        filteredMaterializedViews: [
            (s) => [s.enrichedMaterializedViews, s.searchTerm],
            (views: DataWarehouseSavedQuery[], searchTerm: string): DataWarehouseSavedQuery[] => {
                if (!searchTerm) {
                    return views
                }
                return views.filter((v) => v.name.toLowerCase().includes(searchTerm.toLowerCase()))
            },
        ],
        visibleMaterializedViews: [
            (s) => [s.filteredMaterializedViews, s.materializedViewsCurrentPage],
            (views: DataWarehouseSavedQuery[], currentPage: number): DataWarehouseSavedQuery[] => {
                const startIndex = (currentPage - 1) * PAGE_SIZE
                const endIndex = startIndex + PAGE_SIZE
                return views.slice(startIndex, endIndex)
            },
        ],
        visibleViews: [
            (s) => [s.filteredViews, s.viewsCurrentPage],
            (views: DataWarehouseSavedQuery[], currentPage: number): DataWarehouseSavedQuery[] => {
                const startIndex = (currentPage - 1) * PAGE_SIZE
                const endIndex = startIndex + PAGE_SIZE
                return views.slice(startIndex, endIndex)
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        deleteView: ({ viewId }) => {
            LemonDialog.open({
                title: 'Delete view?',
                description: 'Are you sure you want to delete this view? This action cannot be undone.',
                primaryButton: {
                    children: 'Delete',
                    status: 'danger',
                    onClick: () => {
                        actions.deleteDataWarehouseSavedQuery(viewId)
                        lemonToast.success('View deleted successfully')
                    },
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        runMaterialization: ({ viewId }) => {
            actions.runDataWarehouseSavedQuery(viewId)
        },
        loadDataWarehouseSavedQueriesSuccess: () => {
            // Load data for initially visible items
            actions.loadVisibleData()
        },
        setMaterializedViewsPage: () => {
            // Load data when page changes
            actions.loadVisibleData()
        },
        setViewsPage: () => {
            // Load data when page changes
            actions.loadVisibleData()
        },
        setSearchTerm: () => {
            // Load data when search changes (pagination resets to page 1)
            actions.loadVisibleData()
        },
        loadVisibleData: () => {
            // Get IDs of all currently visible items
            const visibleMaterializedViewIds = values.visibleMaterializedViews.map((v) => v.id)
            const visibleViewIds = values.visibleViews.map((v) => v.id)

            // Load dependencies for materialized views (if not already loaded)
            if (visibleMaterializedViewIds.length > 0) {
                actions.loadDependenciesForMaterializedViews(visibleMaterializedViewIds)
                actions.loadRunHistoryForViews(visibleMaterializedViewIds)
            }

            // Load dependencies for regular views (if not already loaded)
            if (visibleViewIds.length > 0) {
                actions.loadDependenciesForViews(visibleViewIds)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        // If views are already loaded (e.g., from cache), load visible data immediately
        if (values.dataWarehouseSavedQueries.length > 0) {
            actions.loadVisibleData()
        }
    }),
])
