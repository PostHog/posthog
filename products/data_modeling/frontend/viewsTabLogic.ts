import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import type { DataWarehouseSavedQuerySummary } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { teamLogic } from 'scenes/teamLogic'

import type {
    DatabaseSchemaEndpointTable,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaViewTable,
} from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DataModelingEdge,
    DataModelingNode,
    DataWarehouseSavedQueryRunHistory,
} from '~/types'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'
import {
    ParsedLineageSearch,
    nodeIdsForLineageSearch,
    parseLineageSearch,
} from 'products/data_modeling/frontend/lineage/lineageSearch'
import { ModelListRow, groupEndpointVersions } from 'products/data_modeling/frontend/modelList'
import {
    matchesMaterializationStatus,
    MaterializationStatusFilter,
    parseDatabaseSearch,
} from 'products/data_warehouse/frontend/shared/filterMaterializedViewsByStatus'
import { endpointsList, endpointsVersionsList } from 'products/endpoints/frontend/generated/api'
import type { EndpointResponseApi, EndpointVersionResponseApi } from 'products/endpoints/frontend/generated/api.schemas'

export const PAGE_SIZE = 25

export type ViewTypeFilter = 'all' | 'materialized' | 'view' | 'endpoint'

export interface viewsTabLogicValues {
    currentTeamId: number | null
    endpointDataGeneration: number
    modelEndpoints: EndpointResponseApi[]
    modelEndpointVersions: Record<string, EndpointVersionResponseApi[]>
    modelEndpointVersionsLoading: boolean
    modelEndpointsLoading: boolean
    endpointsError: boolean
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
    filteredViews: ModelListRow[]
    lineageNames: Set<string> | null
    parsedSearch: ParsedLineageSearch
    runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
    runHistoryMapLoading: boolean
    searchTerm: string
    searchText: string
    materializationStatusFilters: MaterializationStatusFilter[]
    typeFilter: ViewTypeFilter
    viewsLoading: boolean
    sorting: Sorting | null
    expandedEndpointNames: string[]
    visibleModelRows: ModelListRow[]
    visibleViews: ModelListRow[]
}

export interface viewsTabLogicActions {
    loadCurrentTeamSuccess: (
        currentTeam: import('~/types').TeamPublicType | null,
        payload?: any
    ) => { currentTeam: import('~/types').TeamPublicType | null; payload?: any }
    resetEndpointModels: () => { value: true }
    loadDataWarehouseSavedQueries: () => any
    addMaterializingViews: (viewIds: string[]) => { viewIds: string[] }
    suggestionAccepted: (
        viewId: string,
        startsMaterializing: boolean
    ) => { viewId: string; startsMaterializing: boolean }
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
        viewsLoading: (dataWarehouseSavedQueriesLoading: boolean, modelEndpointsLoading: boolean) => boolean
        enrichedViews: (
            dataWarehouseSavedQueries: DataWarehouseSavedQuerySummary[],
            runHistoryMap: Record<string, DataWarehouseSavedQueryRunHistory[]>
        ) => DataWarehouseSavedQuerySummary[]
        filteredViews: (
            enrichedViews: DataWarehouseSavedQuerySummary[],
            parsedSearch: ParsedLineageSearch,
            lineageNames: Set<string> | null,
            typeFilter: ViewTypeFilter,
            modelEndpoints: EndpointResponseApi[],
            modelEndpointVersions: Record<string, EndpointVersionResponseApi[]>,
            materializationStatusFilters: MaterializationStatusFilter[]
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
            teamLogic,
            ['loadCurrentTeamSuccess'],
            dataWarehouseViewsLogic,
            [
                'deleteDataWarehouseSavedQuery',
                'runDataWarehouseSavedQuery',
                'loadDataWarehouseSavedQueriesSuccess',
                'loadDataWarehouseSavedQueries',
                'addMaterializingViews',
            ],
            databaseTableListLogic,
            ['loadDatabase'],
        ],
    })),
    actions({
        resetEndpointModels: true,
        suggestionAccepted: (viewId: string, startsMaterializing: boolean) => ({ viewId, startsMaterializing }),
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
        openAccessControlModal: (view: DataWarehouseSavedQuerySummary) => ({ view }),
        closeAccessControlModal: true,
    }),
    reducers({
        endpointDataGeneration: [0, { resetEndpointModels: (generation) => generation + 1 }],
        sorting: [null as Sorting | null, { setSorting: (_, { sorting }) => sorting }],
        expandedEndpointNames: [
            [] as string[],
            {
                resetEndpointModels: () => [],
                toggleEndpointExpanded: (state, { name }) =>
                    state.includes(name) ? state.filter((item) => item !== name) : [...state, name],
            },
        ],
        endpointsError: [
            false,
            {
                resetEndpointModels: () => false,
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
                resetEndpointModels: () => 1,
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
            null as DataWarehouseSavedQuerySummary | null,
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
                    const teamId = values.currentTeamId
                    const generation = values.endpointDataGeneration
                    if (!teamId || !userHasAccess(AccessControlResourceType.Endpoint, AccessControlLevel.Viewer)) {
                        return {}
                    }
                    const versions: EndpointVersionResponseApi[] = []
                    try {
                        let hasMore = true
                        while (hasMore) {
                            const page = await endpointsVersionsList(String(teamId), name, {
                                limit: 100,
                                offset: versions.length,
                            })
                            if (generation !== values.endpointDataGeneration || teamId !== values.currentTeamId) {
                                return values.modelEndpointVersions
                            }
                            versions.push(...page.results)
                            hasMore = !!page.next && page.results.length > 0
                        }
                    } catch (error) {
                        if (generation !== values.endpointDataGeneration || teamId !== values.currentTeamId) {
                            return values.modelEndpointVersions
                        }
                        throw error
                    }
                    return { ...values.modelEndpointVersions, [name]: versions }
                },
            },
        ],
        modelEndpoints: [
            [] as EndpointResponseApi[],
            {
                loadModelEndpoints: async (_: void, breakpoint) => {
                    const teamId = values.currentTeamId
                    const generation = values.endpointDataGeneration
                    const endpoints: EndpointResponseApi[] = []
                    if (!teamId || !userHasAccess(AccessControlResourceType.Endpoint, AccessControlLevel.Viewer)) {
                        return endpoints
                    }
                    try {
                        let hasMore = true
                        while (hasMore) {
                            const page = await endpointsList(String(teamId), {
                                limit: 100,
                                offset: endpoints.length,
                            })
                            breakpoint()
                            if (generation !== values.endpointDataGeneration || teamId !== values.currentTeamId) {
                                return values.modelEndpoints
                            }
                            endpoints.push(...page.results)
                            hasMore = !!page.next && page.results.length > 0
                        }
                    } catch (error) {
                        breakpoint()
                        if (generation !== values.endpointDataGeneration || teamId !== values.currentTeamId) {
                            return values.modelEndpoints
                        }
                        throw error
                    }
                    return endpoints
                },
            },
        ],
        runHistoryMap: [
            {} as Record<string, DataWarehouseSavedQueryRunHistory[]>,
            {
                loadRunHistory: async ({ viewIds }) => {
                    const generation = values.endpointDataGeneration
                    const teamId = values.currentTeamId
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

                    if (generation !== values.endpointDataGeneration || teamId !== values.currentTeamId) {
                        return values.runHistoryMap
                    }
                    const newMap = { ...values.runHistoryMap }
                    results.forEach(({ viewId, data }) => {
                        newMap[viewId] = data
                    })
                    return newMap
                },
            },
        ],
    })),
    reducers({
        modelEndpoints: { resetEndpointModels: () => [] },
        modelEndpointVersions: { resetEndpointModels: () => ({}) },
        runHistoryMap: { resetEndpointModels: () => ({}) },
    }),
    selectors({
        viewsLoading: [
            (s) => [s.dataWarehouseSavedQueriesLoading, s.modelEndpointsLoading],
            (loading: boolean, endpointsLoading: boolean): boolean => loading || endpointsLoading,
        ],
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
        searchText: [(s) => [s.searchTerm], (searchTerm: string): string => parseDatabaseSearch(searchTerm).searchText],
        materializationStatusFilters: [
            (s) => [s.searchTerm],
            (searchTerm: string): MaterializationStatusFilter[] =>
                parseDatabaseSearch(searchTerm).materializationStatusFilters,
        ],
        parsedSearch: [(s) => [s.searchText], (searchText: string) => parseLineageSearch(searchText)],

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
                s.materializationStatusFilters,
            ],
            (
                views: DataWarehouseSavedQuerySummary[],
                parsedSearch: ParsedLineageSearch,
                lineageNames: Set<string> | null,
                typeFilter: ViewTypeFilter,
                publishedEndpoints: EndpointResponseApi[],
                publishedVersions: Record<string, EndpointVersionResponseApi[]>,
                materializationStatusFilters: MaterializationStatusFilter[]
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
                    if (
                        !versions.some((version) => matchesMaterializationStatus(version, materializationStatusFilters))
                    ) {
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
    listeners(({ actions, values, cache }) => ({
        loadCurrentTeamSuccess: () => {
            if (cache.modelEndpointTeamId !== values.currentTeamId) {
                cache.modelEndpointTeamId = values.currentTeamId
                actions.resetEndpointModels()
                actions.loadModelEndpoints()
            }
        },
        toggleEndpointExpanded: ({ name }) => {
            if (values.expandedEndpointNames.includes(name)) {
                if (!values.modelEndpointVersions[name]) {
                    actions.loadModelEndpointVersions(name)
                }
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
        suggestionAccepted: ({ viewId, startsMaterializing }) => {
            if (startsMaterializing) {
                actions.addMaterializingViews([viewId])
            }
            actions.loadDataWarehouseSavedQueries()
        },
        runMaterialization: ({ viewId }) => {
            actions.runDataWarehouseSavedQuery(viewId)
        },
        loadDataWarehouseSavedQueriesSuccess: () => {
            const lastPage = Math.max(1, Math.ceil(values.filteredViews.length / PAGE_SIZE))
            if (values.currentPage > lastPage) {
                actions.setPage(lastPage)
                return
            }
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
    afterMount(({ actions, values, cache }) => {
        cache.modelEndpointTeamId = values.currentTeamId
        actions.loadModelEndpoints()
        if (values.dataWarehouseSavedQueries.length > 0) {
            actions.loadVisibleData()
        }
        if (!values.database) {
            actions.loadDatabase()
        }
    }),
])
