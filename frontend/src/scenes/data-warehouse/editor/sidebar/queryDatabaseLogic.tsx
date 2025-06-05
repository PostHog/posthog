import { IconDatabase, IconDocument } from '@posthog/icons'
import { LemonMenuItem, lemonToast } from '@posthog/lemon-ui'
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

export const queryDatabaseLogic = kea<queryDatabaseLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'queryDatabaseLogic']),
    actions({
        selectSchema: (schema: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery) => ({
            schema,
        }),
        setExpandedFolders: (folderIds: string[]) => ({ folderIds }),
        setExpandedSearchFolders: (folderIds: string[]) => ({ folderIds }),
        toggleFolderOpen: (folderId: string, isExpanded: boolean) => ({ folderId, isExpanded }),
        setTreeRef: (ref: React.RefObject<LemonTreeRef> | null) => ({ ref }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        clearSearch: true,
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
            ],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueryMapById'],
        ],
        actions: [
            viewLinkLogic,
            ['toggleEditJoinModal'],
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
            null as React.RefObject<LemonTreeRef> | null,
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
                    const posthogChildren: TreeDataItem[] = relevantPosthogTables.map(([table, matches]) => {
                        const tableChildren: TreeDataItem[] = []

                        if ('fields' in table) {
                            Object.values(table.fields).forEach((field: DatabaseSchemaField) => {
                                tableChildren.push({
                                    id: `search-col-${table.name}-${field.name}`,
                                    name: `${field.name} (${field.type})`,
                                    type: 'node',
                                    record: {
                                        type: 'column',
                                    },
                                })
                            })
                        }

                        const tableId = `search-table-${table.name}`
                        // Don't expand the table itself, only its parent

                        return {
                            id: tableId,
                            name: table.name,
                            type: 'node',
                            icon: <IconDocument />,
                            record: {
                                type: 'table',
                                searchMatches: matches,
                            },
                            children: tableChildren,
                        }
                    })

                    const posthogFolderId = 'search-posthog'
                    expandedIds.push(posthogFolderId)

                    sourcesChildren.push({
                        id: posthogFolderId,
                        name: 'PostHog',
                        icon: <DataWarehouseSourceIcon type="PostHog" size="xsmall" disableTooltip />,
                        type: 'node',
                        record: {
                            type: 'source-folder',
                            sourceType: 'PostHog',
                        },
                        children: posthogChildren,
                    })
                }

                // Add data warehouse tables grouped by source
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
                    const sourceChildren: TreeDataItem[] = tablesWithMatches.map(([table, matches]) => {
                        const tableChildren: TreeDataItem[] = []

                        if ('fields' in table) {
                            Object.values(table.fields).forEach((field: DatabaseSchemaField) => {
                                tableChildren.push({
                                    id: `search-col-${table.name}-${field.name}`,
                                    name: `${field.name} (${field.type})`,
                                    type: 'node',
                                    record: {
                                        type: 'column',
                                    },
                                })
                            })
                        }

                        const tableId = `search-table-${table.name}`
                        // Don't expand the table itself, only its parent

                        return {
                            id: tableId,
                            name: table.name,
                            type: 'node',
                            icon: <IconDatabase />,
                            record: {
                                type: 'table',
                                searchMatches: matches,
                            },
                            children: tableChildren,
                        }
                    })

                    const sourceFolderId = `search-${sourceType}`
                    expandedIds.push(sourceFolderId)

                    sourcesChildren.push({
                        id: sourceFolderId,
                        name: sourceType,
                        type: 'node',
                        icon: (
                            <DataWarehouseSourceIcon
                                type={
                                    sourceType === 'Self-managed' && tablesWithMatches.length > 0
                                        ? mapUrlToProvider(tablesWithMatches[0][0].url_pattern)
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
                    })
                })

                // Views children
                const viewsChildren: TreeDataItem[] = []

                // Add saved queries
                relevantSavedQueries.forEach(([view, matches]) => {
                    const viewChildren: TreeDataItem[] = []

                    if ('columns' in view && view.columns) {
                        Object.values(view.columns).forEach((column: DatabaseSchemaField) => {
                            viewChildren.push({
                                id: `search-col-${view.name}-${column.name}`,
                                name: `${column.name} (${column.type})`,
                                type: 'node',
                                record: {
                                    type: 'column',
                                },
                            })
                        })
                    }

                    const viewId = `search-view-${view.id}`
                    // Don't expand the view itself, only its parent

                    viewsChildren.push({
                        id: viewId,
                        name: view.name,
                        type: 'node',
                        icon: <IconDocument />,
                        record: {
                            type: 'view',
                            searchMatches: matches,
                        },
                        children: viewChildren,
                    })
                })

                // Add managed views
                relevantManagedViews.forEach(([view, matches]) => {
                    const viewChildren: TreeDataItem[] = []

                    if ('fields' in view) {
                        Object.values(view.fields).forEach((field: DatabaseSchemaField) => {
                            viewChildren.push({
                                id: `search-col-${view.name}-${field.name}`,
                                name: `${field.name} (${field.type})`,
                                type: 'node',
                                record: {
                                    type: 'column',
                                },
                            })
                        })
                    }

                    const viewId = `search-view-${view.id}`
                    // Don't expand the view itself, only its parent

                    viewsChildren.push({
                        id: viewId,
                        name: view.name,
                        type: 'node',
                        icon: <IconDatabase />,
                        record: {
                            type: 'view',
                            searchMatches: matches,
                        },
                        children: viewChildren,
                    })
                })

                const searchResults: TreeDataItem[] = []

                if (sourcesChildren.length > 0) {
                    expandedIds.push('search-sources')
                    searchResults.push({
                        id: 'search-sources',
                        name: 'Sources',
                        type: 'node',
                        record: {
                            type: 'sources',
                        },
                        children: sourcesChildren,
                    })
                }

                if (viewsChildren.length > 0) {
                    expandedIds.push('search-views')
                    searchResults.push({
                        id: 'search-views',
                        name: 'Views',
                        type: 'node',
                        record: {
                            type: 'views',
                        },
                        children: viewsChildren,
                    })
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
            ],
            (
                posthogTables: DatabaseSchemaTable[],
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
                managedViews: DatabaseSchemaManagedViewTable[],
                searchTerm: string,
                searchTreeData: TreeDataItem[]
            ): TreeDataItem[] => {
                if (searchTerm) {
                    return searchTreeData
                }

                const sourcesChildren: TreeDataItem[] = []

                // Add PostHog tables in a PostHog folder
                const posthogChildren: TreeDataItem[] = []
                posthogTables.forEach((table) => {
                    const tableChildren: TreeDataItem[] = []

                    if ('fields' in table) {
                        Object.values(table.fields).forEach((field) => {
                            tableChildren.push({
                                id: `col-${table.name}-${field.name}`,
                                name: `${field.name} (${field.type})`,
                                type: 'node',
                                record: {
                                    type: 'column',
                                },
                            })
                        })
                    }

                    posthogChildren.push({
                        id: `table-${table.name}`,
                        name: table.name,
                        type: 'node',
                        icon: <IconDocument />,
                        record: {
                            type: 'table',
                        },
                        children: tableChildren,
                    })
                })

                if (posthogChildren.length > 0) {
                    sourcesChildren.push({
                        id: 'posthog-folder',
                        name: 'PostHog',
                        icon: <DataWarehouseSourceIcon type="PostHog" size="xsmall" disableTooltip />,
                        type: 'node',
                        record: {
                            type: 'source-folder',
                            sourceType: 'PostHog',
                        },
                        children: posthogChildren,
                    })
                }

                const tablesBySourceType = dataWarehouseTables.reduce(
                    (acc: Record<string, DatabaseSchemaDataWarehouseTable[]>, table) => {
                        if (table.source) {
                            if (!acc[table.source.source_type]) {
                                acc[table.source.source_type] = []
                            }
                            acc[table.source.source_type].push(table)
                        } else {
                            if (!acc['Self-managed']) {
                                acc['Self-managed'] = []
                            }
                            acc['Self-managed'].push(table)
                        }
                        return acc
                    },
                    {}
                )

                // Add data warehouse tables
                Object.entries(tablesBySourceType).forEach(([sourceType, tables]) => {
                    const sourceChildren: TreeDataItem[] = []

                    tables.forEach((table) => {
                        const tableChildren: TreeDataItem[] = []
                        if ('fields' in table) {
                            Object.values(table.fields).forEach((field) => {
                                tableChildren.push({
                                    id: `col-${table.name}-${field.name}`,
                                    name: `${field.name} (${field.type})`,
                                    type: 'node',
                                    record: {
                                        type: 'column',
                                    },
                                })
                            })
                        }

                        sourceChildren.push({
                            id: `table-${table.name}`,
                            name: table.name,
                            type: 'node',
                            icon: <IconDatabase />,
                            record: {
                                type: 'table',
                            },
                            children: tableChildren,
                        })
                    })

                    sourcesChildren.push({
                        id: `source-${sourceType}`,
                        name: sourceType,
                        type: 'node',
                        icon: (
                            <DataWarehouseSourceIcon
                                type={
                                    sourceType === 'Self-managed' && tables.length > 0
                                        ? mapUrlToProvider(tables[0].url_pattern)
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
                    })
                })

                // Views children
                const viewsChildren: TreeDataItem[] = []

                dataWarehouseSavedQueries.forEach((view) => {
                    const viewChildren: TreeDataItem[] = []

                    if ('columns' in view && view.columns) {
                        Object.values(view.columns).forEach((column) => {
                            viewChildren.push({
                                id: `col-${view.name}-${column.name}`,
                                name: `${column.name} (${column.type})`,
                                type: 'node',
                                record: {
                                    type: 'column',
                                },
                            })
                        })
                    }

                    viewsChildren.push({
                        id: `view-${view.id}`,
                        name: view.name,
                        type: 'node',
                        icon: <IconDocument />,
                        record: {
                            type: 'view',
                        },
                        children: viewChildren,
                    })
                })

                managedViews.forEach((view) => {
                    const viewChildren: TreeDataItem[] = []

                    if ('fields' in view) {
                        Object.values(view.fields).forEach((field) => {
                            viewChildren.push({
                                id: `col-${view.name}-${field.name}`,
                                name: `${field.name} (${field.type})`,
                                type: 'node',
                                record: {
                                    type: 'column',
                                },
                            })
                        })
                    }

                    viewsChildren.push({
                        id: `view-${view.id}`,
                        name: view.name,
                        type: 'node',
                        icon: <IconDatabase />,
                        record: {
                            type: 'view',
                        },
                        children: viewChildren,
                    })
                })

                return [
                    {
                        id: 'sources',
                        name: 'Sources',
                        type: 'node',
                        record: {
                            type: 'sources',
                        },
                        children: sourcesChildren,
                    },
                    {
                        id: 'views',
                        name: 'Views',
                        type: 'node',
                        record: {
                            type: 'views',
                        },
                        children: viewsChildren,
                    },
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
