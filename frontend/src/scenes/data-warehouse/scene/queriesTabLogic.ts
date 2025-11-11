import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

import { DataWarehouseSavedQuery } from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import type { queriesTabLogicType } from './queriesTabLogicType'

export const queriesTabLogic = kea<queriesTabLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'queriesTabLogic']),
    connect(() => ({
        values: [
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueriesLoading'],
        ],
        actions: [
            dataWarehouseViewsLogic,
            ['deleteDataWarehouseSavedQuery', 'runDataWarehouseSavedQuery'],
        ],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        deleteView: (viewId: string) => ({ viewId }),
        runMaterialization: (viewId: string) => ({ viewId }),
        loadDependenciesForViews: (viewIds: string[]) => ({ viewIds }),
        loadRunHistoryForViews: (viewIds: string[]) => ({ viewIds }),
    }),
    reducers({
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    loaders(({ values }) => ({
        dependenciesMap: [
            {} as Record<string, { upstream_count: number; downstream_count: number }>,
            {
                loadDependenciesForViews: async ({ viewIds }) => {
                    const results = await Promise.all(
                        viewIds.map(async (viewId) => {
                            try {
                                const data = await api.dataWarehouseSavedQueries.dependencies(viewId)
                                return { viewId, data }
                            } catch (error) {
                                console.error(`Failed to load dependencies for view ${viewId}:`, error)
                                return { viewId, data: { upstream_count: 0, downstream_count: 0 } }
                            }
                        })
                    )

                    const newMap = { ...values.dependenciesMap }
                    results.forEach(({ viewId, data }) => {
                        newMap[viewId] = data
                    })
                    return newMap
                },
            },
        ],
        runHistoryMap: [
            {} as Record<string, Array<{ status: string; timestamp: string }>>,
            {
                loadRunHistoryForViews: async ({ viewIds }) => {
                    const results = await Promise.all(
                        viewIds.map(async (viewId) => {
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
        viewsLoading: [
            (s) => [s.dataWarehouseSavedQueriesLoading],
            (loading): boolean => loading,
        ],
        enrichedQueries: [
            (s) => [s.dataWarehouseSavedQueries, s.dependenciesMap, s.runHistoryMap],
            (queries, dependenciesMap, runHistoryMap): DataWarehouseSavedQuery[] => {
                return queries.map((query) => ({
                    ...query,
                    upstream_dependency_count: dependenciesMap[query.id]?.upstream_count,
                    downstream_dependency_count: dependenciesMap[query.id]?.downstream_count,
                    run_history: runHistoryMap[query.id],
                }))
            },
        ],
        filteredViews: [
            (s) => [s.enrichedQueries, s.searchTerm],
            (queries, searchTerm): DataWarehouseSavedQuery[] => {
                const views = queries.filter((q) => !q.is_materialized)
                if (!searchTerm) {
                    return views
                }
                return views.filter((v) => v.name.toLowerCase().includes(searchTerm.toLowerCase()))
            },
        ],
        filteredMaterializedViews: [
            (s) => [s.enrichedQueries, s.searchTerm],
            (queries, searchTerm): DataWarehouseSavedQuery[] => {
                const views = queries.filter((q) => q.is_materialized)
                if (!searchTerm) {
                    return views
                }
                return views.filter((v) => v.name.toLowerCase().includes(searchTerm.toLowerCase()))
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
            // Once views are loaded, fetch dependencies and run history
            const allViewIds = values.dataWarehouseSavedQueries.map((q) => q.id)
            const materializedViewIds = values.dataWarehouseSavedQueries.filter((q) => q.is_materialized).map((q) => q.id)

            if (allViewIds.length > 0) {
                actions.loadDependenciesForViews(allViewIds)
            }
            if (materializedViewIds.length > 0) {
                actions.loadRunHistoryForViews(materializedViewIds)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        // If views are already loaded (e.g., from cache), fetch dependencies immediately
        if (values.dataWarehouseSavedQueries.length > 0) {
            const allViewIds = values.dataWarehouseSavedQueries.map((q) => q.id)
            const materializedViewIds = values.dataWarehouseSavedQueries.filter((q) => q.is_materialized).map((q) => q.id)

            if (allViewIds.length > 0) {
                actions.loadDependenciesForViews(allViewIds)
            }
            if (materializedViewIds.length > 0) {
                actions.loadRunHistoryForViews(materializedViewIds)
            }
        }
    }),
])
