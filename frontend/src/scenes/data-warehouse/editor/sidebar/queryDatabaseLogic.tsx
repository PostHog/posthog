import { IconDatabase, IconDocument, IconPlug } from '@posthog/icons'
import { LemonMenuItem, lemonToast } from '@posthog/lemon-ui'
import { Spinner } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { DataWarehouseSourceIcon, mapUrlToProvider } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { FuseSearchMatch } from '~/layout/navigation-3000/sidebars/utils'
import {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaField,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaTable,
} from '~/queries/schema/schema-general'
import { DataWarehouseSavedQuery, DataWarehouseViewLink } from '~/types'

import { dataWarehouseJoinsLogic } from '../../external/dataWarehouseJoinsLogic'
import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { viewLinkLogic } from '../../viewLinkLogic'
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

const isJoined = (field: DatabaseSchemaField): boolean => {
    return field.type === 'view' || field.type === 'lazy_table'
}

const FUSE_OPTIONS: Fuse.IFuseOptions<any> = {
    keys: [{ name: 'name', weight: 2 }],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
}

const posthogTablesFuse = new Fuse<DatabaseSchemaTable>([], FUSE_OPTIONS)
const dataWarehouseTablesFuse = new Fuse<DatabaseSchemaDataWarehouseTable>([], FUSE_OPTIONS)
const savedQueriesFuse = new Fuse<DataWarehouseSavedQuery>([], FUSE_OPTIONS)
const managedViewsFuse = new Fuse<DatabaseSchemaManagedViewTable>([], FUSE_OPTIONS)

// Factory functions for creating tree nodes
const createColumnNode = (tableName: string, field: DatabaseSchemaField, isSearch = false): TreeDataItem => ({
    id: `${isSearch ? 'search-' : ''}col-${tableName}-${field.name}`,
    name: `${field.name} (${field.type})`,
    type: 'node',
    record: {
        type: 'column',
        columnName: field.name,
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

const createViewNode = (
    view: DataWarehouseSavedQuery | DatabaseSchemaManagedViewTable,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false
): TreeDataItem => {
    const viewChildren: TreeDataItem[] = []
    const isManagedView = 'type' in view && view.type === 'managed_view'

    // Add columns/fields
    if ('columns' in view && view.columns) {
        Object.values(view.columns).forEach((column: DatabaseSchemaField) => {
            viewChildren.push(createColumnNode(view.name, column, isSearch))
        })
    } else if ('fields' in view) {
        Object.values(view.fields).forEach((field: DatabaseSchemaField) => {
            viewChildren.push(createColumnNode(view.name, field, isSearch))
        })
    }

    const viewId = `${isSearch ? 'search-' : ''}view-${view.id}`

    return {
        id: viewId,
        name: view.name,
        type: 'node',
        icon: isManagedView ? <IconDatabase /> : <IconDocument />,
        record: {
            type: 'view',
            view: view,
            isSavedQuery: !isManagedView,
            ...(matches && { searchMatches: matches }),
        },
        children: viewChildren,
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
    type: 'sources' | 'views',
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

    return {
        id: isSearch ? `search-${type}` : type,
        name: type === 'sources' ? 'Sources' : 'Views',
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
                'databaseLoading',
            ],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueryMapById', 'dataWarehouseSavedQueriesLoading'],
        ],
        actions: [
            viewLinkLogic,
            ['toggleEditJoinModal', 'toggleJoinTableModal'],
            databaseTableListLogic,
            ['loadDatabase'],
            dataWarehouseJoinsLogic,
            ['loadJoins'],
        ],
    })),
    reducers({
        selectedSchema: [
            null as DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null,
            {
                selectSchema: (_, { schema }) => schema,
            },
        ],
        expandedFolders: [
            ['sources', 'views'] as string[], // Default expanded folders
            {
                setExpandedFolders: (_, { folderIds }) => folderIds,
            },
        ],
        expandedSearchFolders: [
            ['sources', 'views', 'search-posthog', 'search-datawarehouse', 'search-views'] as string[],
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
    }),
    selectors(({ actions }) => ({
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
        searchTreeData: [
            (s) => [
                s.relevantPosthogTables,
                s.relevantDataWarehouseTables,
                s.relevantSavedQueries,
                s.relevantManagedViews,
                s.searchTerm,
            ],
            (
                relevantPosthogTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][],
                relevantDataWarehouseTables: [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][],
                relevantSavedQueries: [DataWarehouseSavedQuery, FuseSearchMatch[] | null][],
                relevantManagedViews: [DatabaseSchemaManagedViewTable, FuseSearchMatch[] | null][],
                searchTerm: string
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

                // Add saved queries
                relevantSavedQueries.forEach(([view, matches]) => {
                    viewsChildren.push(createViewNode(view, matches, true))
                })

                // Add managed views
                relevantManagedViews.forEach(([view, matches]) => {
                    viewsChildren.push(createViewNode(view, matches, true))
                })

                const searchResults: TreeDataItem[] = []

                if (sourcesChildren.length > 0) {
                    expandedIds.push('search-sources')
                    searchResults.push(createTopLevelFolderNode('sources', sourcesChildren, true, <IconPlug />))
                }

                if (viewsChildren.length > 0) {
                    expandedIds.push('search-views')
                    searchResults.push(createTopLevelFolderNode('views', viewsChildren, true))
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
                s.dataWarehouseTables,
                s.dataWarehouseSavedQueries,
                s.managedViews,
                s.searchTerm,
                s.searchTreeData,
                s.databaseLoading,
                s.dataWarehouseSavedQueriesLoading,
            ],
            (
                posthogTables: DatabaseSchemaTable[],
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
                managedViews: DatabaseSchemaManagedViewTable[],
                searchTerm: string,
                searchTreeData: TreeDataItem[],
                databaseLoading: boolean,
                dataWarehouseSavedQueriesLoading: boolean
            ): TreeDataItem[] => {
                if (searchTerm) {
                    return searchTreeData
                }

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

                // Add loading indicator for views if still loading
                if (
                    dataWarehouseSavedQueriesLoading &&
                    dataWarehouseSavedQueries.length === 0 &&
                    managedViews.length === 0
                ) {
                    viewsChildren.push({
                        id: 'views-loading/',
                        name: 'Loading...',
                        displayName: <>Loading...</>,
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })
                } else {
                    // Add saved queries
                    dataWarehouseSavedQueries.forEach((view) => {
                        viewsChildren.push(createViewNode(view))
                    })

                    // Add managed views
                    managedViews.forEach((view) => {
                        viewsChildren.push(createViewNode(view))
                    })
                }

                return [
                    createTopLevelFolderNode('sources', sourcesChildren, false, <IconPlug />),
                    createTopLevelFolderNode('views', viewsChildren),
                ]
            },
        ],
        sidebarOverlayTreeItems: [
            (s) => [
                s.selectedSchema,
                s.joins,
                s.posthogTablesMap,
                s.dataWarehouseTablesMap,
                s.dataWarehouseSavedQueryMapById,
                s.viewsMapById,
            ],
            (
                selectedSchema,
                joins,
                posthogTablesMap,
                dataWarehouseTablesMap,
                dataWarehouseSavedQueryMapById,
                viewsMapById
            ): TreeItem[] => {
                if (selectedSchema === null) {
                    return []
                }
                let table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null =
                    null
                if (isPostHogTable(selectedSchema)) {
                    table = posthogTablesMap[selectedSchema.name]
                } else if (isDataWarehouseTable(selectedSchema)) {
                    table = dataWarehouseTablesMap[selectedSchema.name]
                } else if (isManagedViewTable(selectedSchema)) {
                    table = viewsMapById[selectedSchema.id]
                } else if (isViewTable(selectedSchema)) {
                    table = dataWarehouseSavedQueryMapById[selectedSchema.id]
                }

                if (table == null) {
                    return []
                }

                const relevantJoins = joins.filter((join) => join.source_table_name === table!.name)
                const joinsByFieldName = relevantJoins.reduce((acc, join) => {
                    if (join.field_name) {
                        acc[join.field_name] = join
                    }
                    return acc
                }, {} as Record<string, DataWarehouseViewLink>)

                const menuItems = (field: DatabaseSchemaField): LemonMenuItem[] => {
                    return isJoined(field) && joinsByFieldName[field.name]
                        ? [
                              {
                                  label: 'Edit',
                                  onClick: () => {
                                      actions.toggleEditJoinModal(joinsByFieldName[field.name])
                                  },
                              },
                              {
                                  label: 'Delete join',
                                  status: 'danger',
                                  onClick: () => {
                                      const join = joinsByFieldName[field.name]
                                      void deleteWithUndo({
                                          endpoint: api.dataWarehouseViewLinks.determineDeleteEndpoint(),
                                          object: {
                                              id: join.id,
                                              name: `${join.field_name} on ${join.source_table_name}`,
                                          },
                                          callback: () => {
                                              actions.loadDatabase()
                                              actions.loadJoins()
                                          },
                                      }).catch((e) => {
                                          lemonToast.error(`Failed to delete warehouse view link: ${e.detail}`)
                                      })
                                  },
                              },
                          ]
                        : []
                }

                if ('fields' in table) {
                    return Object.values(table.fields).map((field) => ({
                        name: field.name,
                        type: field.type,
                        menuItems: menuItems(field),
                    }))
                }

                if ('columns' in table) {
                    return Object.values(table.columns).map((column) => ({
                        name: column.name,
                        type: column.type,
                        menuItems: menuItems(column),
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
    })),
    subscriptions({
        posthogTables: (posthogTables: DatabaseSchemaTable[]) => {
            posthogTablesFuse.setCollection(posthogTables)
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
    }),
])
