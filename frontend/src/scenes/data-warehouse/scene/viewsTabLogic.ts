import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import type { DataWarehouseSavedQuerySummary } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { DataModelingEdge, DataModelingNode, DataWarehouseSavedQueryRunHistory } from '~/types'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'
import {
    ParsedLineageSearch,
    nodeIdsForLineageSearch,
    parseLineageSearch,
} from 'products/data_modeling/frontend/lineage/lineageSearch'

import type { FeatureFlagsSet } from '../../../lib/logic/featureFlagLogic'
import type {
    DatabaseSchemaEndpointTable,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaViewTable,
} from '../../../queries/schema/schema-general'
import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'

export const PAGE_SIZE = 10

export type ViewTypeFilter = 'all' | 'materialized' | 'view'

export interface viewsTabLogicValues {
    dataWarehouseSavedQueries: DataWarehouseSavedQuerySummary[] // dataWarehouseViewsLogic
    dataWarehouseSavedQueriesLoading: boolean // dataWarehouseViewsLogic
    database: Required<DatabaseSchemaQueryResponse> | null // databaseTableListLogic
    viewsMapById: Record<string, DatabaseSchemaEndpointTable | DatabaseSchemaManagedViewTable | DatabaseSchemaViewTable> // databaseTableListLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    nodes: DataModelingNode[] // modelsLineageLogic
    nodesLoading: boolean // modelsLineageLogic
    edges: DataModelingEdge[] // modelsLineageLogic
    edgesLoading: boolean // modelsLineageLogic
    accessControlModalOpen: boolean
    currentPage: number
    editingAccessControlView: DataWarehouseSavedQuerySummary | null
    enrichedViews: DataWarehouseSavedQuerySummary[]
    filteredViews: DataWarehouseSavedQuerySummary[]
    lineageNames: Set<string> | null
    parsedSearch: ParsedLineageSearch
    runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
    runHistoryMapLoading: boolean
    searchTerm: string
    typeFilter: ViewTypeFilter
    viewsLoading: boolean
    visibleViews: DataWarehouseSavedQuerySummary[]
}

export interface viewsTabLogicActions {
    deleteDataWarehouseSavedQuery: (viewId: string) => string // dataWarehouseViewsLogic
    runDataWarehouseSavedQuery: (
        viewId: string,
        fullRefresh?: boolean | undefined
    ) => {
        fullRefresh: boolean | undefined
        viewId: string
    } // dataWarehouseViewsLogic
    loadDataWarehouseSavedQueriesSuccess: (
        dataWarehouseSavedQueries: DataWarehouseSavedQuerySummary[],
        payload?: any
    ) => any // dataWarehouseViewsLogic
    loadDatabase: (
        args_0?:
            | {
                  force?: boolean
                  shallow?: boolean
              }
            | undefined
    ) => {
        force?: boolean
        shallow?: boolean
    } // databaseTableListLogic
    closeAccessControlModal: () => {
        value: true
    }
    deleteView: (viewId: string) => {
        viewId: string
    }
    loadRunHistory: (viewIds: string[]) => {
        viewIds: string[]
    }
    loadRunHistoryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRunHistorySuccess: (
        runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>,
        payload?: {
            viewIds: string[]
        }
    ) => {
        runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
        payload?: {
            viewIds: string[]
        }
    }
    loadVisibleData: () => {
        value: true
    }
    openAccessControlModal: (view: DataWarehouseSavedQuerySummary) => {
        view: DataWarehouseSavedQuerySummary
    }
    runMaterialization: (viewId: string) => {
        viewId: string
    }
    setPage: (page: number) => {
        page: number
    }
    setSearchTerm: (searchTerm: string) => {
        searchTerm: string
    }
    setTypeFilter: (typeFilter: ViewTypeFilter) => {
        typeFilter: ViewTypeFilter
    }
}

export interface viewsTabLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        viewsLoading: (dataWarehouseSavedQueriesLoading: boolean) => boolean
        enrichedViews: (
            dataWarehouseSavedQueries: DataWarehouseSavedQuerySummary[],
            runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
        ) => DataWarehouseSavedQuerySummary[]
        filteredViews: (
            enrichedViews: DataWarehouseSavedQuerySummary[],
            searchTerm: string,
            typeFilter: ViewTypeFilter
        ) => DataWarehouseSavedQuerySummary[]
        visibleViews: (
            filteredViews: DataWarehouseSavedQuerySummary[],
            currentPage: number
        ) => DataWarehouseSavedQuerySummary[]
    }
}

export type viewsTabLogicType = MakeLogicType<
    viewsTabLogicValues,
    viewsTabLogicActions,
    Record<string, any>,
    viewsTabLogicMeta
>

export const viewsTabLogic = kea<viewsTabLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'viewsTabLogic']),
    connect(() => ({
        values: [
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueriesLoading'],
            featureFlagLogic,
            ['featureFlags'],
            databaseTableListLogic,
            ['database', 'viewsMapById'],
            lineageDataLogic,
            ['nodes', 'nodesLoading', 'edges', 'edgesLoading'],
        ],
        actions: [
            dataWarehouseViewsLogic,
            ['deleteDataWarehouseSavedQuery', 'runDataWarehouseSavedQuery', 'loadDataWarehouseSavedQueriesSuccess'],
            databaseTableListLogic,
            ['loadDatabase'],
        ],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setTypeFilter: (typeFilter: ViewTypeFilter) => ({ typeFilter }),
        setPage: (page: number) => ({ page }),
        deleteView: (viewId: string) => ({ viewId }),
        runMaterialization: (viewId: string) => ({ viewId }),
        loadRunHistory: (viewIds: string[]) => ({ viewIds }),
        loadVisibleData: true,
        openAccessControlModal: (view: DataWarehouseSavedQuerySummary) => ({ view }),
        closeAccessControlModal: true,
    }),
    reducers({
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        typeFilter: [
            'all' as ViewTypeFilter,
            {
                setTypeFilter: (_, { typeFilter }) => typeFilter,
            },
        ],
        currentPage: [
            1 as number,
            {
                setPage: (_, { page }) => page,
                setSearchTerm: () => 1,
                setTypeFilter: () => 1,
            },
        ],
        accessControlModalOpen: [
            false,
            {
                openAccessControlModal: () => true,
                closeAccessControlModal: () => false,
            },
        ],
        editingAccessControlView: [
            null as DataWarehouseSavedQuerySummary | null,
            {
                openAccessControlModal: (_, { view }) => view,
                closeAccessControlModal: () => null,
            },
        ],
    }),
    loaders(({ values }) => ({
        runHistoryMap: [
            {} as Record<string, DataWarehouseSavedQueryRunHistory[]>,
            {
                loadRunHistory: async ({ viewIds }) => {
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
        viewsLoading: [(s) => [s.dataWarehouseSavedQueriesLoading], (loading: boolean): boolean => loading],
        enrichedViews: [
            (s) => [s.dataWarehouseSavedQueries, s.runHistoryMap],
            (
                queries: DataWarehouseSavedQuerySummary[],
                runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
            ): DataWarehouseSavedQuerySummary[] =>
                queries.map((query) => ({
                    ...query,
                    run_history: query.is_materialized ? runHistoryMap[query.id] : undefined,
                })),
        ],
        parsedSearch: [(s) => [s.searchTerm], (searchTerm: string) => parseLineageSearch(searchTerm)],

        // Lineage names the rows to keep; the graph keys on node id, this table on view name.
        lineageNames: [
            (s) => [s.nodes, s.edges, s.nodesLoading, s.edgesLoading, s.parsedSearch],
            (
                nodes: DataModelingNode[],
                edges: DataModelingEdge[],
                nodesLoading: boolean,
                edgesLoading: boolean,
                parsedSearch: ParsedLineageSearch
            ): Set<string> | null => {
                if (parsedSearch.mode !== 'search' && (nodesLoading || edgesLoading)) {
                    return null
                }
                const reached = nodeIdsForLineageSearch(nodes, edges, parsedSearch)
                return reached && new Set(nodes.filter((node) => reached.has(node.id)).map((node) => node.name))
            },
        ],

        filteredViews: [
            (s) => [s.enrichedViews, s.parsedSearch, s.lineageNames, s.typeFilter],
            (
                views: DataWarehouseSavedQuerySummary[],
                parsedSearch: ParsedLineageSearch,
                lineageNames: Set<string> | null,
                typeFilter: ViewTypeFilter
            ): DataWarehouseSavedQuerySummary[] => {
                const term = parsedSearch.term.toLowerCase()
                return views.filter((view) => {
                    if (typeFilter === 'materialized' && !view.is_materialized) {
                        return false
                    }
                    if (typeFilter === 'view' && view.is_materialized) {
                        return false
                    }
                    if (lineageNames) {
                        return lineageNames.has(view.name)
                    }
                    return !term || view.name.toLowerCase().includes(term)
                })
            },
        ],
        visibleViews: [
            (s) => [s.filteredViews, s.currentPage],
            (views: DataWarehouseSavedQuerySummary[], currentPage: number): DataWarehouseSavedQuerySummary[] => {
                const startIndex = (currentPage - 1) * PAGE_SIZE
                return views.slice(startIndex, startIndex + PAGE_SIZE)
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
            actions.loadVisibleData()
        },
        setPage: () => {
            actions.loadVisibleData()
        },
        setSearchTerm: () => {
            actions.loadVisibleData()
        },
        setTypeFilter: () => {
            actions.loadVisibleData()
        },
        loadVisibleData: () => {
            const visible = values.visibleViews
            if (visible.length === 0) {
                return
            }
            const materializedIds = visible.filter((view) => view.is_materialized).map((view) => view.id)
            if (materializedIds.length > 0) {
                actions.loadRunHistory(materializedIds)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.dataWarehouseSavedQueries.length > 0) {
            actions.loadVisibleData()
        }
        if (!values.database) {
            actions.loadDatabase()
        }
    }),
])
