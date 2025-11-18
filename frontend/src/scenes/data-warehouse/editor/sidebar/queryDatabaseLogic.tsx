import Fuse from 'fuse.js'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { IconBolt, IconCode2, IconDatabase, IconDocument, IconPlug, IconPlus } from '@posthog/icons'
import { LemonMenuItem } from '@posthog/lemon-ui'
import { Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { DataWarehouseSourceIcon, mapUrlToProvider } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { FuseSearchMatch } from '~/layout/navigation-3000/sidebars/utils'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaEndpointTable,
    DatabaseSchemaField,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaTable,
} from '~/queries/schema/schema-general'
import {
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryDraft,
    DataWarehouseViewLink,
    FileSystemIconColor,
    QueryTabState,
} from '~/types'

import { dataWarehouseJoinsLogic } from '../../external/dataWarehouseJoinsLogic'
import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { viewLinkLogic } from '../../viewLinkLogic'
import { draftsLogic } from '../draftsLogic'
import type { queryDatabaseLogicType } from './queryDatabaseLogicType'

export type EditorSidebarTreeRef = React.RefObject<LemonTreeRef> | null

const isDataWarehouseTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaDataWarehouseTable => {
    return 'type' in table && table.type === 'data_warehouse'
}

const isPostHogTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaTable => {
    return 'type' in table && table.type === 'posthog'
}

const isSystemTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaTable => {
    return 'type' in table && table.type === 'system'
}

const isViewTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DataWarehouseSavedQuery => {
    return 'query' in table
}

const isManagedViewTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaManagedViewTable => {
    return 'type' in table && table.type === 'managed_view'
}

const isEndpointTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaEndpointTable => {
    return 'type' in table && table.type === 'endpoint'
}

export const isJoined = (field: DatabaseSchemaField): boolean => {
    return field.type === 'view' || field.type === 'lazy_table'
}

const FUSE_OPTIONS: Fuse.IFuseOptions<any> = {
    keys: [{ name: 'name', weight: 2 }],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
}

const posthogTablesFuse = new Fuse<DatabaseSchemaTable>([], FUSE_OPTIONS)
const systemTablesFuse = new Fuse<DatabaseSchemaTable>([], FUSE_OPTIONS)
const dataWarehouseTablesFuse = new Fuse<DatabaseSchemaDataWarehouseTable>([], FUSE_OPTIONS)
const savedQueriesFuse = new Fuse<DataWarehouseSavedQuery>([], FUSE_OPTIONS)
const managedViewsFuse = new Fuse<DatabaseSchemaManagedViewTable>([], FUSE_OPTIONS)
const endpointTablesFuse = new Fuse<DatabaseSchemaEndpointTable>([], FUSE_OPTIONS)
const draftsFuse = new Fuse<DataWarehouseSavedQueryDraft>([], FUSE_OPTIONS)
// Factory functions for creating tree nodes
const createColumnNode = (tableName: string, field: DatabaseSchemaField, isSearch = false): TreeDataItem => ({
    id: `${isSearch ? 'search-' : ''}col-${tableName}-${field.name}`,
    name: `${field.name} (${field.type})`,
    type: 'node',
    record: {
        type: 'column',
        columnName: field.name,
        field,
        table: tableName,
    },
})

const createTableNode = (
    table: DatabaseSchemaTable | DatabaseSchemaDataWarehouseTable,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false
): TreeDataItem => {
    const tableChildren: TreeDataItem[] = []

    if ('fields' in table) {
        Object.values(table.fields).forEach((field: DatabaseSchemaField) => {
            tableChildren.push(createColumnNode(table.name, field, isSearch))
        })
    }

    const tableId = `${isSearch ? 'search-' : ''}table-${table.name}`
    const isPostHogTable = 'type' in table && table.type === 'posthog'

    return {
        id: tableId,
        name: table.name,
        type: 'node',
        icon: isPostHogTable ? <IconDocument /> : <IconDatabase />,
        record: {
            type: 'table',
            table: table,
            row_count: table.row_count,
            ...(matches && { searchMatches: matches }),
        },
        children: tableChildren,
    }
}

const createDraftNode = (
    draft: DataWarehouseSavedQueryDraft,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false
): TreeDataItem => {
    return {
        id: `${isSearch ? 'search-' : ''}draft-${draft.id}`,
        name: draft.name,
        type: 'node',
        icon: <IconDocument />,
        record: {
            id: draft.id,
            type: 'draft',
            draft: draft,
            ...(matches && { searchMatches: matches }),
        },
    }
}

const createViewNode = (
    view: DataWarehouseSavedQuery,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false
): TreeDataItem => {
    const viewChildren: TreeDataItem[] = []
    const isMaterializedView = view.is_materialized === true
    const isManagedViewsetView = view.managed_viewset_kind !== null
    const isManagedView = 'type' in view && view.type === 'managed_view'

    Object.values(view.columns).forEach((column: DatabaseSchemaField) => {
        viewChildren.push(createColumnNode(view.name, column, isSearch))
    })

    const viewId = `${isSearch ? 'search-' : ''}view-${view.id}`

    return {
        id: viewId,
        name: view.name,
        type: 'node',
        icon: isManagedViewsetView ? (
            <IconBolt />
        ) : isManagedView || isMaterializedView ? (
            <IconDatabase />
        ) : (
            <IconDocument />
        ),
        record: {
            type: 'view',
            view: view,
            isSavedQuery: !isManagedView,
            ...(matches && { searchMatches: matches }),
        },
        children: viewChildren,
    }
}

const createManagedViewNode = (
    managedView: DatabaseSchemaManagedViewTable,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false
): TreeDataItem => {
    const viewChildren: TreeDataItem[] = []

    Object.values(managedView.fields).forEach((field: DatabaseSchemaField) => {
        viewChildren.push(createColumnNode(managedView.name, field, isSearch))
    })

    const managedViewId = `${isSearch ? 'search-' : ''}managed-view-${managedView.id}`

    return {
        id: managedViewId,
        name: managedView.name,
        type: 'node',
        icon: <IconDatabase />,
        record: {
            type: 'managed-view',
            view: managedView,
            ...(matches && { searchMatches: matches }),
        },
        children: viewChildren,
    }
}

const createEndpointNode = (
    endpoint: DatabaseSchemaEndpointTable,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false
): TreeDataItem => {
    const endpointChildren: TreeDataItem[] = []

    Object.values(endpoint.fields).forEach((field: DatabaseSchemaField) => {
        endpointChildren.push(createColumnNode(endpoint.name, field, isSearch))
    })

    const endpointId = `${isSearch ? 'search-' : ''}endpoint-${endpoint.id}`

    return {
        id: endpointId,
        name: endpoint.name,
        type: 'node',
        icon: <IconCode2 />,
        record: {
            type: 'endpoint',
            endpoint: endpoint,
            ...(matches && { searchMatches: matches }),
        },
        children: endpointChildren,
    }
}

const createSourceFolderNode = (
    sourceType: string,
    tables: (DatabaseSchemaTable | DatabaseSchemaDataWarehouseTable)[],
    matches: [any, FuseSearchMatch[] | null][] = [],
    isSearch = false
): TreeDataItem => {
    const sourceChildren: TreeDataItem[] = []

    if (isSearch && matches.length > 0) {
        matches.forEach(([table, tableMatches]) => {
            sourceChildren.push(createTableNode(table, tableMatches, true))
        })
    } else {
        tables.forEach((table) => {
            sourceChildren.push(createTableNode(table, null, false))
        })
    }

    const sourceFolderId = isSearch
        ? `search-${sourceType === 'PostHog' ? 'posthog' : sourceType}`
        : `source-${sourceType === 'PostHog' ? 'posthog' : sourceType}`

    return {
        id: sourceFolderId,
        name: sourceType,
        type: 'node',
        icon: (
            <DataWarehouseSourceIcon
                type={
                    sourceType === 'Self-managed' && (tables.length > 0 || matches.length > 0)
                        ? mapUrlToProvider(
                              tables.length > 0
                                  ? (tables[0] as DatabaseSchemaDataWarehouseTable).url_pattern
                                  : (matches[0][0] as DatabaseSchemaDataWarehouseTable).url_pattern
                          )
                        : sourceType
                }
                size="xsmall"
                disableTooltip
            />
        ),
        record: {
            type: 'source-folder',
            sourceType,
        },
        children: sourceChildren,
    }
}

const createTopLevelFolderNode = (
    type: 'sources' | 'views' | 'managed-views' | 'endpoints' | 'drafts',
    children: TreeDataItem[],
    isSearch = false,
    icon?: JSX.Element
): TreeDataItem => {
    let finalChildren = children

    // Add empty folder child if views folder is empty
    if (type === 'views' && children.length === 0) {
        finalChildren = [
            {
                id: `${isSearch ? 'search-' : ''}views-folder-empty/`,
                name: 'Empty folder',
                type: 'empty-folder',
                record: {
                    type: 'empty-folder',
                },
            },
        ]
    }

    if (type === 'drafts' && children.length === 0) {
        finalChildren = [
            {
                id: `${isSearch ? 'search-' : ''}drafts-folder-empty/`,
                name: 'Empty folder',
                type: 'empty-folder',
                record: {
                    type: 'empty-folder',
                },
            },
        ]
    }

    if (type === 'managed-views' && children.length === 0) {
        finalChildren = [
            {
                id: `${isSearch ? 'search-' : ''}managed-views-folder-empty/`,
                name: 'Empty folder',
                type: 'empty-folder',
                record: {
                    type: 'empty-folder',
                },
            },
        ]
    }

    if (type === 'endpoints' && children.length === 0) {
        finalChildren = [
            {
                id: `${isSearch ? 'search-' : ''}endpoints-folder-empty/`,
                name: 'Empty folder',
                type: 'empty-folder',
                record: {
                    type: 'empty-folder',
                },
            },
        ]
    }

    return {
        id: isSearch ? `search-${type}` : type,
        name:
            type === 'sources'
                ? 'Sources'
                : type === 'views'
                  ? 'Views'
                  : type === 'drafts'
                    ? 'Drafts'
                    : type === 'endpoints'
                      ? 'Endpoints'
                      : 'Managed Views',
        type: 'node',
        icon: icon,
        record: {
            type,
        },
        children: finalChildren,
    }
}

export const queryDatabaseLogic = kea<queryDatabaseLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'queryDatabaseLogic']),
    actions({
        selectSchema: (schema: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery) => ({
            schema,
        }),
        setExpandedFolders: (folderIds: string[]) => ({ folderIds }),
        setExpandedSearchFolders: (folderIds: string[]) => ({ folderIds }),
        toggleFolderOpen: (folderId: string, isExpanded: boolean) => ({ folderId, isExpanded }),
        setTreeRef: (ref: EditorSidebarTreeRef | null) => ({ ref }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        clearSearch: true,
        selectSourceTable: (tableName: string) => ({ tableName }),
        setSyncMoreNoticeDismissed: (dismissed: boolean) => ({ dismissed }),
        setEditingDraft: (draftId: string) => ({ draftId }),
        openUnsavedQuery: (record: Record<string, any>) => ({ record }),
        deleteUnsavedQuery: (record: Record<string, any>) => ({ record }),
    }),
    connect(() => ({
        values: [
            dataWarehouseJoinsLogic,
            ['joins', 'joinsLoading'],
            databaseTableListLogic,
            [
                'posthogTables',
                'dataWarehouseTables',
                'posthogTablesMap',
                'dataWarehouseTablesMap',
                'viewsMapById',
                'managedViews',
                'endpointTables',
                'databaseLoading',
                'systemTables',
                'systemTablesMap',
            ],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueryMapById', 'dataWarehouseSavedQueriesLoading'],
            draftsLogic,
            ['drafts', 'draftsResponseLoading', 'hasMoreDrafts'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
        ],
        actions: [
            viewLinkLogic,
            ['toggleEditJoinModal', 'toggleJoinTableModal'],
            dataWarehouseSettingsLogic,
            ['deleteJoin'],
            draftsLogic,
            ['loadDrafts', 'renameDraft', 'loadMoreDrafts'],
        ],
    })),
    reducers({
        editingDraftId: [
            null as string | null,
            {
                setEditingDraft: (_, { draftId }) => draftId,
            },
        ],
        selectedSchema: [
            null as DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null,
            {
                selectSchema: (_, { schema }) => schema,
            },
        ],
        expandedFolders: [
            ['sources', 'views', 'managed-views', 'endpoints'] as string[], // Default expanded folders
            {
                setExpandedFolders: (_, { folderIds }) => folderIds,
            },
        ],
        expandedSearchFolders: [
            [
                'sources',
                'views',
                'managed-views',
                'endpoints',
                'search-posthog',
                'search-system',
                'search-datawarehouse',
                'search-views',
                'search-managed-views',
                'search-endpoints',
            ] as string[],
            {
                setExpandedSearchFolders: (_, { folderIds }) => folderIds,
            },
        ],
        treeRef: [
            null as EditorSidebarTreeRef,
            {
                setTreeRef: (_, { ref }) => ref,
            },
        ],

        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                clearSearch: () => '',
            },
        ],
        syncMoreNoticeDismissed: [
            false,
            { persist: true },
            {
                setSyncMoreNoticeDismissed: (_, { dismissed }) => dismissed,
            },
        ],
    }),
    loaders(({ values }) => ({
        queryTabState: [
            null as QueryTabState | null,
            {
                loadQueryTabState: async () => {
                    if (!values.user) {
                        return null
                    }
                    try {
                        return await api.queryTabState.user(values.user?.uuid)
                    } catch (e) {
                        console.error(e)
                        return null
                    }
                },
                deleteUnsavedQuery: async ({ record }) => {
                    const { queryTabState } = values
                    if (!values.user || !queryTabState || !queryTabState.state || !queryTabState.id) {
                        return null
                    }
                    try {
                        const { editorModelsStateKey } = queryTabState.state
                        const queries = JSON.parse(editorModelsStateKey)
                        const newState = {
                            ...queryTabState,
                            state: {
                                ...queryTabState.state,
                                editorModelsStateKey: JSON.stringify(
                                    queries.filter((q: any) => q.name !== record.name && q.path !== record.path)
                                ),
                            },
                        }

                        await api.queryTabState.update(queryTabState.id, newState)

                        return newState
                    } catch (e) {
                        console.error(e)
                        return queryTabState
                    }
                },
            },
        ],
    })),
    selectors(({ actions }) => ({
        hasNonPosthogSources: [
            (s) => [s.dataWarehouseTables],
            (dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]): boolean => {
                return dataWarehouseTables.length > 0
            },
        ],
        relevantPosthogTables: [
            (s) => [s.posthogTables, s.searchTerm],
            (
                posthogTables: DatabaseSchemaTable[],
                searchTerm: string
            ): [DatabaseSchemaTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return posthogTablesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return posthogTables.map((table) => [table, null])
            },
        ],
        relevantSystemTables: [
            (s) => [s.systemTables, s.searchTerm],
            (
                systemTables: DatabaseSchemaTable[],
                searchTerm: string
            ): [DatabaseSchemaTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return systemTablesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return systemTables.map((table) => [table, null])
            },
        ],
        relevantDataWarehouseTables: [
            (s) => [s.dataWarehouseTables, s.searchTerm],
            (
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                searchTerm: string
            ): [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return dataWarehouseTablesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return dataWarehouseTables.map((table) => [table, null])
            },
        ],
        relevantSavedQueries: [
            (s) => [s.dataWarehouseSavedQueries, s.searchTerm],
            (
                dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
                searchTerm: string
            ): [DataWarehouseSavedQuery, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return savedQueriesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return dataWarehouseSavedQueries.map((query) => [query, null])
            },
        ],
        relevantManagedViews: [
            (s) => [s.managedViews, s.searchTerm],
            (
                managedViews: DatabaseSchemaManagedViewTable[],
                searchTerm: string
            ): [DatabaseSchemaManagedViewTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return managedViewsFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return managedViews.map((view) => [view, null])
            },
        ],
        relevantEndpointTables: [
            (s) => [s.endpointTables, s.searchTerm],
            (
                endpointTables: DatabaseSchemaEndpointTable[],
                searchTerm: string
            ): [DatabaseSchemaEndpointTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return endpointTablesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return endpointTables.map((table) => [table, null])
            },
        ],
        relevantDrafts: [
            (s) => [s.drafts, s.searchTerm],
            (
                drafts: DataWarehouseSavedQueryDraft[],
                searchTerm: string
            ): [DataWarehouseSavedQueryDraft, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return draftsFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return drafts.map((draft) => [draft, null])
            },
        ],
        searchTreeData: [
            (s) => [
                s.relevantPosthogTables,
                s.relevantSystemTables,
                s.relevantDataWarehouseTables,
                s.relevantSavedQueries,
                s.relevantManagedViews,
                s.relevantEndpointTables,
                s.relevantDrafts,
                s.searchTerm,
                s.featureFlags,
            ],
            (
                relevantPosthogTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][],
                relevantSystemTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][],
                relevantDataWarehouseTables: [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][],
                relevantSavedQueries: [DataWarehouseSavedQuery, FuseSearchMatch[] | null][],
                relevantManagedViews: [DatabaseSchemaManagedViewTable, FuseSearchMatch[] | null][],
                relevantEndpointTables: [DatabaseSchemaEndpointTable, FuseSearchMatch[] | null][],
                relevantDrafts: [DataWarehouseSavedQueryDraft, FuseSearchMatch[] | null][],
                searchTerm: string,
                featureFlags: FeatureFlagsSet
            ): TreeDataItem[] => {
                if (!searchTerm) {
                    return []
                }

                const sourcesChildren: TreeDataItem[] = []
                const expandedIds: string[] = []

                // Add PostHog tables
                if (relevantPosthogTables.length > 0) {
                    expandedIds.push('search-posthog')
                    sourcesChildren.push(createSourceFolderNode('PostHog', [], relevantPosthogTables, true))
                }

                // Add System tables
                if (relevantSystemTables.length > 0) {
                    expandedIds.push('search-system')
                    sourcesChildren.push(createSourceFolderNode('System', [], relevantSystemTables, true))
                }

                // Group data warehouse tables by source type
                const tablesBySourceType = relevantDataWarehouseTables.reduce(
                    (
                        acc: Record<string, [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][]>,
                        [table, matches]
                    ) => {
                        const sourceType = table.source?.source_type || 'Self-managed'
                        if (!acc[sourceType]) {
                            acc[sourceType] = []
                        }
                        acc[sourceType].push([table, matches])
                        return acc
                    },
                    {}
                )

                Object.entries(tablesBySourceType).forEach(([sourceType, tablesWithMatches]) => {
                    expandedIds.push(`search-${sourceType}`)
                    sourcesChildren.push(createSourceFolderNode(sourceType, [], tablesWithMatches, true))
                })

                // Create views children
                const viewsChildren: TreeDataItem[] = []
                const managedViewsChildren: TreeDataItem[] = []
                const endpointChildren: TreeDataItem[] = []
                const draftsChildren: TreeDataItem[] = []

                // Add saved queries
                relevantSavedQueries.forEach(([view, matches]) => {
                    viewsChildren.push(createViewNode(view, matches, true))
                })

                // Add managed views
                relevantManagedViews.forEach(([view, matches]) => {
                    managedViewsChildren.push(createManagedViewNode(view, matches, true))
                })

                // Add endpoints
                if (featureFlags[FEATURE_FLAGS.ENDPOINTS]) {
                    relevantEndpointTables.forEach(([endpoint, matches]) => {
                        endpointChildren.push(createEndpointNode(endpoint, matches, true))
                    })
                }

                // Add drafts
                if (featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS]) {
                    relevantDrafts.forEach(([draft, matches]) => {
                        draftsChildren.push(createDraftNode(draft, matches, true))
                    })
                }

                const searchResults: TreeDataItem[] = []

                if (sourcesChildren.length > 0) {
                    expandedIds.push('search-sources')
                    searchResults.push(createTopLevelFolderNode('sources', sourcesChildren, true, <IconPlug />))
                }

                if (viewsChildren.length > 0) {
                    expandedIds.push('search-views')
                    searchResults.push(createTopLevelFolderNode('views', viewsChildren, true))
                }

                if (managedViewsChildren.length > 0 && !featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]) {
                    expandedIds.push('search-managed-views')
                    searchResults.push(createTopLevelFolderNode('managed-views', managedViewsChildren, true))
                }

                if (endpointChildren.length > 0) {
                    expandedIds.push('search-endpoints')
                    searchResults.push(createTopLevelFolderNode('endpoints', endpointChildren, true))
                }

                // TODO: this needs to moved to the backend
                if (draftsChildren.length > 0) {
                    expandedIds.push('search-drafts')
                    searchResults.push(createTopLevelFolderNode('drafts', draftsChildren, true))
                }

                // Auto-expand only parent folders, not the matching nodes themselves
                setTimeout(() => {
                    actions.setExpandedSearchFolders(expandedIds)
                }, 0)

                return searchResults
            },
        ],
        treeData: [
            (s) => [
                s.posthogTables,
                s.systemTables,
                s.dataWarehouseTables,
                s.dataWarehouseSavedQueries,
                s.managedViews,
                s.endpointTables,
                s.databaseLoading,
                s.dataWarehouseSavedQueriesLoading,
                s.drafts,
                s.draftsResponseLoading,
                s.hasMoreDrafts,
                s.featureFlags,
                s.queryTabState,
            ],
            (
                posthogTables: DatabaseSchemaTable[],
                systemTables: DatabaseSchemaTable[],
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
                managedViews: DatabaseSchemaManagedViewTable[],
                endpointTables: DatabaseSchemaEndpointTable[],
                databaseLoading: boolean,
                dataWarehouseSavedQueriesLoading: boolean,
                drafts: DataWarehouseSavedQueryDraft[],
                draftsResponseLoading: boolean,
                hasMoreDrafts: boolean,
                featureFlags: FeatureFlagsSet,
                queryTabState: QueryTabState | null
            ): TreeDataItem[] => {
                const sourcesChildren: TreeDataItem[] = []

                // Add loading indicator for sources if still loading
                if (databaseLoading && posthogTables.length === 0 && dataWarehouseTables.length === 0) {
                    sourcesChildren.push({
                        id: 'sources-loading/',
                        name: 'Loading...',
                        displayName: <>Loading...</>,
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })
                } else {
                    // Add PostHog tables
                    if (posthogTables.length > 0) {
                        sourcesChildren.push(createSourceFolderNode('PostHog', posthogTables))
                    }

                    // Add System tables
                    if (systemTables.length > 0) {
                        systemTables.sort((a, b) => a.name.localeCompare(b.name))
                        sourcesChildren.push(createSourceFolderNode('System', systemTables))
                    }

                    // Group data warehouse tables by source type
                    const tablesBySourceType = dataWarehouseTables.reduce(
                        (acc: Record<string, DatabaseSchemaDataWarehouseTable[]>, table) => {
                            const sourceType = table.source?.source_type || 'Self-managed'
                            if (!acc[sourceType]) {
                                acc[sourceType] = []
                            }
                            acc[sourceType].push(table)
                            return acc
                        },
                        {}
                    )

                    // Add data warehouse tables
                    Object.entries(tablesBySourceType).forEach(([sourceType, tables]) => {
                        sourcesChildren.push(createSourceFolderNode(sourceType, tables))
                    })
                }

                // Create views children
                const viewsChildren: TreeDataItem[] = []
                const managedViewsChildren: TreeDataItem[] = []
                const endpointChildren: TreeDataItem[] = []

                // Add loading indicator for views if still loading
                if (
                    dataWarehouseSavedQueriesLoading &&
                    dataWarehouseSavedQueries.length === 0 &&
                    managedViews.length === 0 &&
                    endpointTables.length === 0
                ) {
                    viewsChildren.push({
                        id: 'views-loading/',
                        name: 'Loading...',
                        displayName: <>Loading...</>,
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })

                    managedViewsChildren.push({
                        id: 'managed-views-loading/',
                        name: 'Loading...',
                        displayName: <>Loading...</>,
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })
                    if (featureFlags[FEATURE_FLAGS.ENDPOINTS]) {
                        endpointChildren.push({
                            id: 'endpoints-loading/',
                            name: 'Loading...',
                            displayName: <>Loading...</>,
                            icon: <Spinner />,
                            disableSelect: true,
                            type: 'loading-indicator',
                        })
                    }
                } else {
                    // Add saved queries
                    dataWarehouseSavedQueries.forEach((view) => {
                        viewsChildren.push(createViewNode(view))
                    })

                    // Add managed views
                    managedViews.forEach((view) => {
                        managedViewsChildren.push(createManagedViewNode(view))
                    })

                    // Add endpoints
                    if (featureFlags[FEATURE_FLAGS.ENDPOINTS]) {
                        endpointTables.forEach((endpoint) => {
                            endpointChildren.push(createEndpointNode(endpoint))
                        })
                    }
                }

                viewsChildren.sort((a, b) => a.name.localeCompare(b.name))
                managedViewsChildren.sort((a, b) => a.name.localeCompare(b.name))
                endpointChildren.sort((a, b) => a.name.localeCompare(b.name))

                const states = queryTabState?.state?.editorModelsStateKey
                const unsavedChildren: TreeDataItem[] = []
                let i = 1
                if (states) {
                    try {
                        for (const state of JSON.parse(states)) {
                            unsavedChildren.push({
                                id: `unsaved-${i++}`,
                                name: state.name || 'Unsaved query',
                                type: 'node',
                                icon: <IconDocument />,
                                record: { type: 'unsaved-query', ...state },
                            })
                        }
                    } catch {
                        // do nothing
                    }
                }

                const draftsChildren: TreeDataItem[] = []

                if (featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS]) {
                    if (draftsResponseLoading && drafts.length === 0) {
                        draftsChildren.push({
                            id: 'drafts-loading/',
                            name: 'Loading...',
                            displayName: <>Loading...</>,
                            icon: <Spinner />,
                            disableSelect: true,
                            type: 'loading-indicator',
                        })
                    } else {
                        drafts.forEach((draft) => {
                            draftsChildren.push(createDraftNode(draft))
                        })

                        if (drafts.length > 0 && draftsResponseLoading) {
                            draftsChildren.push({
                                id: 'drafts-loading/',
                                name: 'Loading...',
                                displayName: <>Loading...</>,
                                icon: <Spinner />,
                                disableSelect: true,
                                type: 'loading-indicator',
                            })
                        } else if (hasMoreDrafts) {
                            draftsChildren.push({
                                id: 'drafts-load-more/',
                                name: 'Load more...',
                                displayName: <>Load more...</>,
                                icon: <IconPlus />,
                                onClick: () => {
                                    actions.loadMoreDrafts()
                                },
                            })
                        }
                    }
                }

                return [
                    {
                        id: 'new-query',
                        name: 'SQL editor',
                        type: 'node',
                        icon: iconForType('sql_editor', [
                            'var(--color-product-data-warehouse-light)',
                        ] as FileSystemIconColor),
                        onClick: () => {
                            newInternalTab(urls.sqlEditor())
                        },
                        record: {
                            type: 'sql',
                        },
                    } as TreeDataItem,
                    createTopLevelFolderNode('sources', sourcesChildren, false, <IconPlug />),
                    ...(featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS]
                        ? [createTopLevelFolderNode('drafts', draftsChildren, false)]
                        : []),
                    ...(unsavedChildren.length > 0
                        ? [
                              {
                                  id: 'unsaved-folder',
                                  name: 'Unsaved queries',
                                  type: 'node',
                                  icon: <IconDocument />,
                                  record: {
                                      type: 'unsaved-folder',
                                  },
                                  children: unsavedChildren,
                              } as TreeDataItem,
                          ]
                        : []),
                    createTopLevelFolderNode('views', viewsChildren),
                    ...(featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]
                        ? []
                        : [createTopLevelFolderNode('managed-views', managedViewsChildren)]),
                    ...(featureFlags[FEATURE_FLAGS.ENDPOINTS]
                        ? [createTopLevelFolderNode('endpoints', endpointChildren)]
                        : []),
                ]
            },
        ],
        joinsByFieldName: [
            (s) => [s.joins],
            (joins: DataWarehouseViewLink[]): Record<string, DataWarehouseViewLink> => {
                return joins.reduce(
                    (acc, join) => {
                        if (join.field_name && join.source_table_name) {
                            acc[`${join.source_table_name}.${join.field_name}`] = join
                        }
                        return acc
                    },
                    {} as Record<string, DataWarehouseViewLink>
                )
            },
        ],
        sidebarOverlayTreeItems: [
            (s) => [
                s.selectedSchema,
                s.posthogTablesMap,
                s.systemTablesMap,
                s.dataWarehouseTablesMap,
                s.dataWarehouseSavedQueryMapById,
                s.viewsMapById,
                s.joinsByFieldName,
            ],
            (
                selectedSchema,
                posthogTablesMap,
                systemTablesMap,
                dataWarehouseTablesMap,
                dataWarehouseSavedQueryMapById,
                viewsMapById,
                joinsByFieldName
            ): TreeItem[] => {
                if (selectedSchema === null) {
                    return []
                }
                let table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null =
                    null
                if (isPostHogTable(selectedSchema)) {
                    table = posthogTablesMap[selectedSchema.name]
                } else if (isSystemTable(selectedSchema)) {
                    table = systemTablesMap[selectedSchema.name]
                } else if (isDataWarehouseTable(selectedSchema)) {
                    table = dataWarehouseTablesMap[selectedSchema.name]
                } else if (isManagedViewTable(selectedSchema)) {
                    table = viewsMapById[selectedSchema.id]
                } else if (isViewTable(selectedSchema)) {
                    table = dataWarehouseSavedQueryMapById[selectedSchema.id]
                }

                if (isEndpointTable(selectedSchema)) {
                    table = viewsMapById[selectedSchema.id]
                }

                if (table == null) {
                    return []
                }

                const menuItems = (field: DatabaseSchemaField, tableName: string): LemonMenuItem[] => {
                    return isJoined(field) && joinsByFieldName[`${tableName}.${field.name}`]
                        ? [
                              {
                                  label: 'Edit',
                                  onClick: () => {
                                      actions.toggleEditJoinModal(joinsByFieldName[`${tableName}.${field.name}`])
                                  },
                              },
                              {
                                  label: 'Delete join',
                                  status: 'danger',
                                  onClick: () => {
                                      const join = joinsByFieldName[`${tableName}.${field.name}`]
                                      actions.deleteJoin(join)
                                  },
                              },
                          ]
                        : []
                }

                if ('fields' in table && table !== null) {
                    return Object.values(table.fields).map((field) => ({
                        name: field.name,
                        type: field.type,
                        menuItems: menuItems(field, table?.name ?? ''), // table cant be null, but the typechecker is confused
                    }))
                }

                if ('columns' in table && table !== null) {
                    return Object.values(table.columns).map((column) => ({
                        name: column.name,
                        type: column.type,
                        menuItems: menuItems(column, table?.name ?? ''), // table cant be null, but the typechecker is confused
                    }))
                }
                return []
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        toggleFolderOpen: ({ folderId }) => {
            const expandedFolders = values.searchTerm ? values.expandedSearchFolders : values.expandedFolders
            const setExpanded = values.searchTerm ? actions.setExpandedSearchFolders : actions.setExpandedFolders

            if (expandedFolders.find((f) => f === folderId)) {
                setExpanded(expandedFolders.filter((f) => f !== folderId))
            } else {
                setExpanded([...expandedFolders, folderId])
            }
        },
        selectSourceTable: ({ tableName }) => {
            // Connect to viewLinkLogic actions
            viewLinkLogic.actions.selectSourceTable(tableName)
            viewLinkLogic.actions.toggleJoinTableModal()
        },
        openUnsavedQuery: ({ record }) => {
            if (record.insight) {
                sceneLogic.actions.newTab(urls.sqlEditor(undefined, undefined, record.insight.short_id))
            } else if (record.view) {
                sceneLogic.actions.newTab(urls.sqlEditor(undefined, record.view.id))
            } else {
                sceneLogic.actions.newTab(urls.sqlEditor(record.query))
            }
        },
    })),
    subscriptions({
        posthogTables: (posthogTables: DatabaseSchemaTable[]) => {
            posthogTablesFuse.setCollection(posthogTables)
        },
        systemTables: (systemTables: DatabaseSchemaTable[]) => {
            systemTablesFuse.setCollection(systemTables)
        },
        dataWarehouseTables: (dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]) => {
            dataWarehouseTablesFuse.setCollection(dataWarehouseTables)
        },
        dataWarehouseSavedQueries: (dataWarehouseSavedQueries: DataWarehouseSavedQuery[]) => {
            savedQueriesFuse.setCollection(dataWarehouseSavedQueries)
        },
        managedViews: (managedViews: DatabaseSchemaManagedViewTable[]) => {
            managedViewsFuse.setCollection(managedViews)
        },
        endpointTables: (endpointTables: DatabaseSchemaEndpointTable[]) => {
            endpointTablesFuse.setCollection(endpointTables)
        },
        drafts: (drafts: DataWarehouseSavedQueryDraft[]) => {
            draftsFuse.setCollection(drafts)
        },
    }),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS]) {
                actions.loadDrafts()
            }
            actions.loadQueryTabState()
        },
    })),
])
