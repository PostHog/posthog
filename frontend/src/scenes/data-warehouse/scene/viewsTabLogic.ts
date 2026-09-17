import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DataModelingEdge, DataModelingNode, DataWarehouseSavedQuery, DataWarehouseSavedQueryRunHistory } from '~/types'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'
import {
    ParsedLineageSearch,
    nodeIdsForLineageSearch,
    parseLineageSearch,
} from 'products/data_modeling/frontend/lineage/lineageSearch'
import { ModelListRow, groupEndpointVersions } from 'products/data_modeling/frontend/modelList'
import { endpointsList, endpointsVersionsList } from 'products/endpoints/frontend/generated/api'
import type { EndpointResponseApi, EndpointVersionResponseApi } from 'products/endpoints/frontend/generated/api.schemas'

import type { FeatureFlagsSet } from '../../../lib/logic/featureFlagLogic'
import type {
    DatabaseSchemaEndpointTable,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaViewTable,
} from '../../../queries/schema/schema-general'
import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'

export const PAGE_SIZE = 25

export type ViewTypeFilter = 'all' | 'materialized' | 'view' | 'endpoint'

export interface viewsTabLogicValues {
    currentTeamId: number | null
    modelEndpoints: EndpointResponseApi[]
    modelEndpointVersions: Record<string, EndpointVersionResponseApi[]>
    modelEndpointVersionsLoading: boolean
    modelEndpointsLoading: boolean
    endpointsError: boolean
    dataWarehouseSavedQueries: DataWarehouseSavedQuery[] // dataWarehouseViewsLogic
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
    editingAccessControlView: DataWarehouseSavedQuery | null
    enrichedViews: DataWarehouseSavedQuery[]
    filteredViews: ModelListRow[]
    lineageNames: Set<string> | null
    parsedSearch: ParsedLineageSearch
    runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
    runHistoryMapLoading: boolean
    searchTerm: string
    typeFilter: ViewTypeFilter
    viewsLoading: boolean
    sorting: Sorting | null
    expandedEndpointNames: string[]
    visibleModelRows: ModelListRow[]
    visibleViews: ModelListRow[]
}

export interface viewsTabLogicActions {
    setSorting: (sorting: Sorting | null) => { sorting: Sorting | null }
    toggleEndpointExpanded: (name: string) => { name: string }
    loadModelEndpointVersions: (name: string) => { name: string }
    loadModelEndpointVersionsSuccess: (
        modelEndpointVersions: Record<string, EndpointVersionResponseApi[]>,
        payload?: { name: string }
    ) => { modelEndpointVersions: Record<string, EndpointVersionResponseApi[]>; payload?: { name: string } }
    loadModelEndpointVersionsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadModelEndpoints: () => void
    loadModelEndpointsSuccess: (modelEndpoints: EndpointResponseApi[]) => { modelEndpoints: EndpointResponseApi[] }
    loadModelEndpointsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }

    deleteDataWarehouseSavedQuery: (viewId: string) => string // dataWarehouseViewsLogic
    runDataWarehouseSavedQuery: (
        viewId: string,
        fullRefresh?: boolean | undefined
    ) => {
        fullRefresh: boolean | undefined
        viewId: string
    } // dataWarehouseViewsLogic
    loadDataWarehouseSavedQueriesSuccess: (dataWarehouseSavedQueries: DataWarehouseSavedQuery[], payload?: any) => any // dataWarehouseViewsLogic
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
    openAccessControlModal: (view: DataWarehouseSavedQuery) => {
        view: DataWarehouseSavedQuery
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
        viewsLoading: (dataWarehouseSavedQueriesLoading: boolean, modelEndpointsLoading: boolean) => boolean
        enrichedViews: (
            dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
            runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
        ) => DataWarehouseSavedQuery[]
        filteredViews: (
            enrichedViews: DataWarehouseSavedQuery[],
            parsedSearch: ParsedLineageSearch,
            lineageNames: Set<string> | null,
            typeFilter: ViewTypeFilter,
            modelEndpoints: EndpointResponseApi[],
            modelEndpointVersions: Record<string, EndpointVersionResponseApi[]>
        ) => ModelListRow[]
        visibleViews: (filteredViews: ModelListRow[], currentPage: number, sorting: Sorting | null) => ModelListRow[]
        visibleModelRows: (views: ModelListRow[], expanded: string[]) => ModelListRow[]
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
            teamLogic,
            ['currentTeamId'],
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
        setSorting: (sorting: Sorting | null) => ({ sorting }),
        toggleEndpointExpanded: (name: string) => ({ name }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setTypeFilter: (typeFilter: ViewTypeFilter) => ({ typeFilter }),
        setPage: (page: number) => ({ page }),
        deleteView: (viewId: string) => ({ viewId }),
        runMaterialization: (viewId: string) => ({ viewId }),
        loadRunHistory: (viewIds: string[]) => ({ viewIds }),
        loadVisibleData: true,
        loadModelEndpointVersions: (name: string) => ({ name }),
        openAccessControlModal: (view: DataWarehouseSavedQuery) => ({ view }),
        closeAccessControlModal: true,
    }),
    reducers({
        sorting: [null as Sorting | null, { setSorting: (_, { sorting }) => sorting }],
        expandedEndpointNames: [
            [] as string[],
            {
                toggleEndpointExpanded: (state, { name }) =>
                    state.includes(name) ? state.filter((item) => item !== name) : [...state, name],
            },
        ],
        endpointsError: [
            false,
            {
                loadModelEndpoints: () => false,
                loadModelEndpointsSuccess: () => false,
                loadModelEndpointsFailure: () => true,
            },
        ],
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
                setSorting: () => 1,
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
            null as DataWarehouseSavedQuery | null,
            {
                openAccessControlModal: (_, { view }) => view,
                closeAccessControlModal: () => null,
            },
        ],
    }),
    loaders(({ values }) => ({
        modelEndpointVersions: [
            {} as Record<string, EndpointVersionResponseApi[]>,
            {
                loadModelEndpointVersions: async ({ name }) => {
                    if (values.modelEndpointVersions[name] || !values.currentTeamId) {
                        return values.modelEndpointVersions
                    }
                    const versions: EndpointVersionResponseApi[] = []
                    let hasMore = true
                    while (hasMore) {
                        const page = await endpointsVersionsList(String(values.currentTeamId), name, {
                            limit: 100,
                            offset: versions.length,
                        })
                        versions.push(...page.results)
                        hasMore = !!page.next && page.results.length > 0
                    }
                    return { ...values.modelEndpointVersions, [name]: versions }
                },
            },
        ],
        modelEndpoints: [
            [] as EndpointResponseApi[],
            {
                loadModelEndpoints: async () => {
                    const endpoints: EndpointResponseApi[] = []
                    if (!values.currentTeamId) {
                        return endpoints
                    }
                    let hasMore = true
                    while (hasMore) {
                        const page = await endpointsList(String(values.currentTeamId), {
                            limit: 100,
                            offset: endpoints.length,
                        })
                        endpoints.push(...page.results)
                        hasMore = !!page.next && page.results.length > 0
                    }
                    return endpoints
                },
            },
        ],
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
        viewsLoading: [
            (s) => [s.dataWarehouseSavedQueriesLoading, s.modelEndpointsLoading],
            (loading: boolean, endpointsLoading: boolean): boolean => loading || endpointsLoading,
        ],
        enrichedViews: [
            (s) => [s.dataWarehouseSavedQueries, s.runHistoryMap],
            (
                queries: DataWarehouseSavedQuery[],
                runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
            ): DataWarehouseSavedQuery[] =>
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
            (s) => [
                s.enrichedViews,
                s.parsedSearch,
                s.lineageNames,
                s.typeFilter,
                s.modelEndpoints,
                s.modelEndpointVersions,
            ],
            (
                views: DataWarehouseSavedQuery[],
                parsedSearch: ParsedLineageSearch,
                lineageNames: Set<string> | null,
                typeFilter: ViewTypeFilter,
                publishedEndpoints: EndpointResponseApi[],
                publishedVersions: Record<string, EndpointVersionResponseApi[]>
            ): ModelListRow[] => {
                const term = parsedSearch.term.toLowerCase()
                return groupEndpointVersions(views, publishedEndpoints, publishedVersions).filter((view) => {
                    const versions = view.endpointVersions ?? [view]
                    if (typeFilter === 'endpoint' && !view.endpoint) {
                        return false
                    }
                    if (typeFilter === 'materialized' && !versions.some((version) => version.is_materialized)) {
                        return false
                    }
                    if (typeFilter === 'view' && (view.is_materialized || !!view.endpoint)) {
                        return false
                    }
                    if (lineageNames) {
                        return versions.some((version) => lineageNames.has(version.name))
                    }
                    return (
                        !term ||
                        versions.some(
                            (version) =>
                                version.name.toLowerCase().includes(term) ||
                                version.endpoint?.name.toLowerCase().includes(term)
                        )
                    )
                })
            },
        ],
        visibleModelRows: [
            (s) => [s.visibleViews, s.expandedEndpointNames],
            (views: ModelListRow[], expanded: string[]): ModelListRow[] =>
                views.flatMap((view) =>
                    view.endpoint && expanded.includes(view.endpoint.name)
                        ? [view, ...(view.endpointVersions ?? [])]
                        : [view]
                ),
        ],
        visibleViews: [
            (s) => [s.filteredViews, s.currentPage, s.sorting],
            (views: ModelListRow[], currentPage: number, sorting: Sorting | null): ModelListRow[] => {
                const startIndex = (currentPage - 1) * PAGE_SIZE
                const sorted = sorting
                    ? [...views].sort((a, b) => {
                          const comparison =
                              sorting.columnKey === 'created_at'
                                  ? dayjs(a.created_at || 0).diff(b.created_at || 0)
                                  : (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                                        b.created_by?.first_name || b.created_by?.email || ''
                                    )
                          return comparison * sorting.order
                      })
                    : views
                return sorted.slice(startIndex, startIndex + PAGE_SIZE)
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        toggleEndpointExpanded: ({ name }) => {
            if (values.expandedEndpointNames.includes(name)) {
                actions.loadModelEndpointVersions(name)
                actions.loadVisibleData()
            }
        },
        loadModelEndpointVersionsSuccess: () => actions.loadVisibleData(),
        loadModelEndpointVersionsFailure: () => {
            lemonToast.error('Could not load endpoint versions. Collapse and expand the model to try again.')
        },
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
        setSorting: () => actions.loadVisibleData(),
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
            const visible = values.visibleModelRows
            if (visible.length === 0) {
                return
            }
            const materializedIds = visible
                .filter((view) => view.is_materialized && !view.isEndpointPlaceholder)
                .map((view) => view.id)
            if (materializedIds.length > 0) {
                actions.loadRunHistory(materializedIds)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadModelEndpoints()
        if (values.dataWarehouseSavedQueries.length > 0) {
            actions.loadVisibleData()
        }
        if (!values.database) {
            actions.loadDatabase()
        }
    }),
])
