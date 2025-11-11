import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { LemonDialog } from '@posthog/lemon-ui'

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
    }),
    reducers({
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    selectors({
        viewsLoading: [
            (s) => [s.dataWarehouseSavedQueriesLoading],
            (loading): boolean => loading,
        ],
        // Mock dependency counts for all views
        enrichedQueries: [
            (s) => [s.dataWarehouseSavedQueries],
            (queries): DataWarehouseSavedQuery[] => {
                // Add mocked dependency counts to each query
                return queries.map((query) => ({
                    ...query,
                    // Mock: Generate semi-random but consistent dependency counts
                    upstream_dependency_count:
                        query.upstream_dependency_count ?? Math.floor(Math.abs(hashString(query.id)) % 5),
                    downstream_dependency_count:
                        query.downstream_dependency_count ?? Math.floor(Math.abs(hashString(query.id + 'down')) % 4),
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
    listeners(({ actions }) => ({
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
    })),
])

// Simple hash function to generate consistent "random" numbers from a string
function hashString(str: string): number {
    let hash = 0
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i)
        hash = (hash << 5) - hash + char
        hash = hash & hash
    }
    return hash
}
