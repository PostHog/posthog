import { IconDatabase, IconDocument, IconPlug } from '@posthog/icons'
import { LemonMenuItem, lemonToast } from '@posthog/lemon-ui'
import { Spinner } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { DataWarehouseSourceIcon, mapUrlToProvider } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { FuseSearchMatch } from '~/layout/navigation-3000/sidebars/utils'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaField,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaTable,
} from '~/queries/schema/schema-general'
import { FileSystemEntry } from '~/queries/schema/schema-general'
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

const FILE_FUSE_OPTIONS: Fuse.IFuseOptions<any> = {
    keys: [{ name: 'path', weight: 2 }],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
}

const UNFILED_SAVED_QUERIES_PATH = 'Unfiled/Saved queries'

const posthogTablesFuse = new Fuse<DatabaseSchemaTable>([], FUSE_OPTIONS)
const dataWarehouseTablesFuse = new Fuse<DatabaseSchemaDataWarehouseTable>([], FUSE_OPTIONS)
const savedQueriesFuse = new Fuse<DataWarehouseSavedQuery>([], FUSE_OPTIONS)
const managedViewsFuse = new Fuse<DatabaseSchemaManagedViewTable>([], FUSE_OPTIONS)
const filesFuse = new Fuse<FileSystemEntry>([], FILE_FUSE_OPTIONS)

// Helper function to sort tree children: folders first, then files, both alphabetically
const sortTreeChildren = (items: TreeDataItem[]): TreeDataItem[] => {
    return items.sort((a, b) => {
        // Folders first (type 'folder'), then files (type 'view')
        if (a.record?.type === 'folder' && b.record?.type !== 'folder') {
            return -1
        }
        if (a.record?.type !== 'folder' && b.record?.type === 'folder') {
            return 1
        }
        // Within same type, sort alphabetically by name
        return a.name.localeCompare(b.name)
    })
}

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
        },
        children: tableChildren,
    }
}

const createManagedViewNode = (
    view: DataWarehouseSavedQuery | DatabaseSchemaManagedViewTable,
    isSearch = false
): TreeDataItem => {
    const viewChildren: TreeDataItem[] = []

    // Add columns/fields
    if ('columns' in view && view.columns) {
        Object.values(view.columns).forEach((column: DatabaseSchemaField) => {
            viewChildren.push(createColumnNode(view.name, column, isSearch))
        })
    } else if ('fields' in view && view.fields) {
        Object.values(view.fields).forEach((field: DatabaseSchemaField) => {
            viewChildren.push(createColumnNode(view.name, field, isSearch))
        })
    }

    const viewId = `${isSearch ? 'search-' : ''}view-${view.id}`

    return {
        id: viewId,
        name: view.name,
        type: 'node',
        icon: <IconDatabase />,
        record: {
            type: 'view',
            view: view,
        },
        children: viewChildren,
    }
}

const createSourceFolderNode = (
    sourceType: string,
    tables: DatabaseSchemaTable[] | DatabaseSchemaDataWarehouseTable[] | DataWarehouseSavedQuery[],
    isSearch = false
): TreeDataItem => {
    const sourceChildren: TreeDataItem[] = []

    if (sourceType === 'Managed views') {
        tables.forEach((view) => {
            if (isManagedViewTable(view)) {
                sourceChildren.push(createManagedViewNode(view, isSearch))
            }
        })
    } else {
        tables.forEach((table) => {
            if (isPostHogTable(table) || isDataWarehouseTable(table)) {
                sourceChildren.push(createTableNode(table, isSearch))
            }
        })
    }

    const sourceFolderId = isSearch
        ? `search-${sourceType === 'PostHog' ? 'posthog' : sourceType}`
        : `source-${sourceType === 'PostHog' ? 'posthog' : sourceType}`

    const icon =
        sourceType == 'Managed views' ? undefined : (
            <DataWarehouseSourceIcon
                type={
                    sourceType === 'Self-managed' && tables.length > 0
                        ? mapUrlToProvider((tables[0] as DatabaseSchemaDataWarehouseTable).url_pattern)
                        : sourceType
                }
                size="xsmall"
                disableTooltip
            />
        )

    return {
        id: sourceFolderId,
        name: sourceType,
        type: 'node',
        icon,
        record: {
            type: 'source-folder',
            sourceType,
        },
        children: sourceChildren,
    }
}

const createSourcesFolderNode = (children: TreeDataItem[], isSearch = false, icon?: JSX.Element): TreeDataItem => ({
    id: isSearch ? `search-sources` : 'sources',
    name: 'Sources',
    type: 'node',
    icon: icon,
    record: {
        type: 'sources',
    },
    children,
})

const createViewNode = (
    file: FileSystemEntry,
    isSearch = false,
    folderStates: any = {},
    folders: any = {},
    dataWarehouseSavedQueryMapById: Record<string, DataWarehouseSavedQuery> = {}
): TreeDataItem => {
    const isFolder = file.type === 'folder'
    const fileId = `${isSearch ? 'search-' : ''}file-${file.path.replace(UNFILED_SAVED_QUERIES_PATH + '/', '')}`

    // Extract file name from path (get the last part after the last '/')
    const fileName = file.path.split('/').pop() || 'Untitled'

    if (isFolder) {
        const folderPath = file.path
        const folderState = folderStates[folderPath]
        const folderContents = folders[folderPath] || []

        let children: TreeDataItem[] = []

        if (folderState === 'loading') {
            children = [
                {
                    id: `${fileId}-loading`,
                    name: 'Loading...',
                    displayName: <>Loading...</>,
                    icon: <Spinner />,
                    disableSelect: true,
                    type: 'loading-indicator',
                },
            ]
        } else if (folderState === 'loaded') {
            if (folderContents.length === 0) {
                children = [
                    {
                        id: `${fileId}-empty`,
                        name: 'Empty folder',
                        displayName: <>Empty folder</>,
                        disableSelect: true,
                        type: 'empty-folder',
                    },
                ]
            } else {
                children = folderContents.map((item: FileSystemEntry) =>
                    createViewNode(item, isSearch, folderStates, folders, dataWarehouseSavedQueryMapById)
                )
                children = sortTreeChildren(children)
            }
        } else {
            // Not loaded yet - show loading indicator (will be triggered on expansion)
            children = [
                {
                    id: `${fileId}-loading`,
                    name: 'Loading...',
                    displayName: <>Loading...</>,
                    icon: <Spinner />,
                    disableSelect: true,
                    type: 'loading-indicator',
                },
            ]
        }

        return {
            id: fileId,
            name: fileName,
            type: 'node',
            record: {
                type: 'folder',
                path: folderPath,
                file: file,
            },
            children,
        }
    }

    // For files, check if it's a saved query and add columns as children
    const fileChildren: TreeDataItem[] = []

    const viewName = file.path.split('/').pop()

    // Try to find the saved query by matching the file name or path
    const savedQuery = Object.values(dataWarehouseSavedQueryMapById).find((query) => viewName === query.name)

    if (savedQuery && savedQuery.columns) {
        Object.values(savedQuery.columns).forEach((column) => {
            fileChildren.push(createColumnNode(savedQuery.name, column, isSearch))
        })
    }

    return {
        id: fileId,
        name: fileName,
        type: 'node',
        icon: <IconDocument />,
        record: {
            type: 'view',
            view: savedQuery,
            isSavedQuery: true,
            file: file,
        },
        children: fileChildren.length > 0 ? fileChildren : undefined,
    }
}

const createViewsFolderNode = (
    files: FileSystemEntry[],
    isSearch = false,
    isLoading = false,
    folderStates: any = {},
    folders: any = {},
    dataWarehouseSavedQueryMapById: Record<string, DataWarehouseSavedQuery> = {}
): TreeDataItem => {
    const filesChildren: TreeDataItem[] = []

    if (isLoading) {
        filesChildren.push({
            id: 'files-loading/',
            name: 'Loading...',
            displayName: <>Loading...</>,
            icon: <Spinner />,
            disableSelect: true,
            type: 'loading-indicator',
        })
    } else {
        files.forEach((file) => {
            filesChildren.push(createViewNode(file, false, folderStates, folders, dataWarehouseSavedQueryMapById))
        })
    }

    const filesFolderId = isSearch ? 'search-views' : 'views'

    return {
        id: filesFolderId,
        name: 'Views',
        type: 'node',
        record: {
            type: 'folder',
        },
        children: sortTreeChildren(filesChildren),
    }
}

// Helper function to build hierarchical folder structure for search results
const buildHierarchicalSearchResults = (
    matchedFiles: [FileSystemEntry, FuseSearchMatch[] | null][],
    folderStates: any,
    folders: any,
    dataWarehouseSavedQueryMapById: Record<string, DataWarehouseSavedQuery>
): { children: TreeDataItem[]; expandedIds: string[] } => {
    const folderMap = new Map<string, TreeDataItem>()
    const rootChildren: TreeDataItem[] = []
    const expandedIds: string[] = []

    // Create a map to track which folders we need
    const neededFolders = new Set<string>()

    // First pass: identify all folder paths we need
    matchedFiles.forEach(([file]) => {
        const relativePath = file.path.replace(UNFILED_SAVED_QUERIES_PATH + '/', '')
        const pathParts = relativePath.split('/')

        // Add all parent folder paths
        for (let i = 0; i < pathParts.length - 1; i++) {
            const folderPath = pathParts.slice(0, i + 1).join('/')
            neededFolders.add(folderPath)
            expandedIds.push(`search-file-${folderPath}`)
        }
    })

    // Second pass: create folder structure
    const sortedFolders = Array.from(neededFolders).sort((a, b) => a.length - b.length)

    sortedFolders.forEach((folderPath) => {
        const fullPath = `${UNFILED_SAVED_QUERIES_PATH}/${folderPath}`
        const pathParts = folderPath.split('/')
        const folderName = pathParts[pathParts.length - 1]
        const parentFolderPath = pathParts.slice(0, -1).join('/')

        const folderNode: TreeDataItem = {
            id: `search-file-${folderPath}`,
            name: folderName,
            type: 'node',
            record: {
                type: 'folder',
                path: fullPath,
            },
            children: [],
        }

        folderMap.set(folderPath, folderNode)

        if (parentFolderPath) {
            // Add to parent folder
            const parentFolder = folderMap.get(parentFolderPath)
            if (parentFolder) {
                parentFolder.children!.push(folderNode)
            }
        } else {
            // Add to root
            rootChildren.push(folderNode)
        }
    })

    // Third pass: add matched files to their folders
    matchedFiles.forEach(([file, _]) => {
        const relativePath = file.path.replace(UNFILED_SAVED_QUERIES_PATH + '/', '')
        const pathParts = relativePath.split('/')
        pathParts.pop() // Remove filename to get parent folder path
        const folderPath = pathParts.join('/')

        const fileNode = createViewNode(file, true, folderStates, folders, dataWarehouseSavedQueryMapById)

        if (folderPath) {
            // Add to folder
            const parentFolder = folderMap.get(folderPath)
            if (parentFolder) {
                parentFolder.children!.push(fileNode)
            }
        } else {
            // Add to root
            rootChildren.push(fileNode)
        }
    })

    // Sort children in all folders to show folders first, then files
    // Sort root children
    const sortedRootChildren = sortTreeChildren(rootChildren)

    // Sort children in all folders
    folderMap.forEach((folder) => {
        if (folder.children) {
            folder.children = sortTreeChildren(folder.children)
        }
    })

    return { children: sortedRootChildren, expandedIds }
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
        setEditingItemId: (id: string) => ({ id }),
        rename: (value: string, item: FileSystemEntry) => ({ value, item }),
        addFolder: true,
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
            projectTreeDataLogic,
            ['viableItems', 'folders', 'folderStates'],
        ],
        actions: [
            viewLinkLogic,
            ['toggleEditJoinModal', 'toggleJoinTableModal'],
            databaseTableListLogic,
            ['loadDatabase'],
            dataWarehouseJoinsLogic,
            ['loadJoins'],
            dataWarehouseViewsLogic,
            ['createDataWarehouseSavedQuerySuccess'],
            projectTreeDataLogic,
            ['loadFolder', 'moveItem', 'queueAction', 'loadUnfiledItems', 'deleteItem'],
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
            ['sources', 'views', 'managed-views'] as string[], // Default expanded folders
            {
                setExpandedFolders: (_, { folderIds }) => folderIds,
            },
        ],
        expandedSearchFolders: [
            ['sources', 'managed-views', 'search-posthog', 'search-datawarehouse', 'search-managed-views'] as string[],
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
        editingItemId: [
            '',
            {
                setEditingItemId: (_, { id }) => id,
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
        unfiledSavedQueryFiles: [
            (s) => [s.viableItems],
            (viableItems: FileSystemEntry[]): FileSystemEntry[] => {
                // Filter files from the "unfiled/saved queries" folder (direct children only)
                const unfiledPath = UNFILED_SAVED_QUERIES_PATH + '/'
                return viableItems.filter((item) => {
                    if (!item.path.startsWith(unfiledPath)) {
                        return false
                    }

                    // Get the relative path after "Unfiled/Saved queries/"
                    const relativePath = item.path.substring(unfiledPath.length)

                    // Only include direct children (no additional slashes in the relative path)
                    // This means the item is directly in the folder, not in a subfolder
                    return !relativePath.includes('/')
                })
            },
        ],
        allUnfiledFiles: [
            (s) => [s.viableItems],
            (viableItems: FileSystemEntry[]): FileSystemEntry[] => {
                // Filter all files from the "unfiled/saved queries" folder at any depth
                const unfiledPath = UNFILED_SAVED_QUERIES_PATH + '/'
                return viableItems.filter((item) => {
                    return item.path.startsWith(unfiledPath) && item.type !== 'folder'
                })
            },
        ],
        unfiledFolders: [
            (s) => [s.viableItems],
            (viableItems: FileSystemEntry[]): FileSystemEntry[] => {
                // Get all folders within the unfiled path (including nested ones)
                const unfiledPath = UNFILED_SAVED_QUERIES_PATH + '/'
                return viableItems.filter((item) => {
                    return item.path.startsWith(unfiledPath) && item.type === 'folder'
                })
            },
        ],
        relevantFiles: [
            (s) => [s.allUnfiledFiles, s.searchTerm],
            (allUnfiledFiles: FileSystemEntry[], searchTerm: string): [FileSystemEntry, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return filesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return allUnfiledFiles.map((file) => [file, null])
            },
        ],
        searchTreeData: [
            (s) => [
                s.relevantPosthogTables,
                s.relevantDataWarehouseTables,
                s.relevantManagedViews,
                s.relevantFiles,
                s.folderStates,
                s.folders,
                s.searchTerm,
                s.dataWarehouseSavedQueryMapById,
            ],
            (
                relevantPosthogTables,
                relevantDataWarehouseTables,
                relevantManagedViews,
                relevantFiles,
                folderStates,
                folders,
                searchTerm,
                dataWarehouseSavedQueryMapById
            ): TreeDataItem[] => {
                if (!searchTerm) {
                    return []
                }

                const sourcesChildren: TreeDataItem[] = []
                const expandedIds: string[] = []
                const posthogTables = relevantPosthogTables.map(([table, _]) => table)
                const managedViews = relevantManagedViews.map(([view, _]) => view)

                // Add PostHog tables
                if (relevantPosthogTables.length > 0) {
                    expandedIds.push('search-posthog')
                    sourcesChildren.push(createSourceFolderNode('PostHog', posthogTables, true))
                }

                // Group data warehouse tables by source type
                const tablesBySourceType = relevantDataWarehouseTables.reduce(
                    (acc: Record<string, DatabaseSchemaDataWarehouseTable[]>, [table, _]) => {
                        const sourceType = table.source?.source_type || 'Self-managed'
                        if (!acc[sourceType]) {
                            acc[sourceType] = []
                        }
                        acc[sourceType].push(table)
                        return acc
                    },
                    {}
                )

                Object.entries(tablesBySourceType).forEach(([sourceType, dataWarehouseTables]) => {
                    expandedIds.push(`search-${sourceType}`)
                    sourcesChildren.push(createSourceFolderNode(sourceType, dataWarehouseTables, true))
                })

                // Add managed views
                if (managedViews.length > 0) {
                    expandedIds.push('search-Managed views')
                    sourcesChildren.push(createSourceFolderNode('Managed views', managedViews, true))
                }

                // Create files children with hierarchical structure
                const filesHierarchy = buildHierarchicalSearchResults(
                    relevantFiles,
                    folderStates,
                    folders,
                    dataWarehouseSavedQueryMapById
                )
                const filesChildren = filesHierarchy.children

                // Add folder expansion IDs from hierarchy
                expandedIds.push(...filesHierarchy.expandedIds)

                const searchResults: TreeDataItem[] = []

                if (sourcesChildren.length > 0) {
                    expandedIds.push('search-sources')
                    searchResults.push(createSourcesFolderNode(sourcesChildren, true, <IconPlug />))
                }

                if (filesChildren.length > 0) {
                    expandedIds.push('search-views')
                    searchResults.push({
                        id: 'search-views',
                        name: 'Views',
                        type: 'node',
                        record: {
                            type: 'folder',
                        },
                        children: filesChildren,
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
                s.unfiledSavedQueryFiles,
                s.folderStates,
                s.folders,
                s.databaseLoading,
                s.dataWarehouseSavedQueriesLoading,
                s.dataWarehouseSavedQueryMapById,
            ],
            (
                posthogTables,
                dataWarehouseTables,
                dataWarehouseSavedQueries,
                managedViews,
                unfiledSavedQueryFiles,
                folderStates,
                folders,
                databaseLoading,
                dataWarehouseSavedQueriesLoading,
                dataWarehouseSavedQueryMapById
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
                    // Add managed views
                    managedViews.forEach((view) => {
                        viewsChildren.push(createManagedViewNode(view))
                    })
                }

                sourcesChildren.push(createSourceFolderNode('Managed views', managedViews))

                // Check if the unfiled folder is loading
                const unfiledFolderPath = UNFILED_SAVED_QUERIES_PATH
                const isFilesLoading =
                    folderStates[unfiledFolderPath] === 'loading' ||
                    (folderStates[unfiledFolderPath] !== 'loaded' && unfiledSavedQueryFiles.length === 0)

                return [
                    createSourcesFolderNode(sourcesChildren, false, <IconPlug />),
                    createViewsFolderNode(
                        unfiledSavedQueryFiles,
                        false,
                        isFilesLoading,
                        folderStates,
                        folders,
                        dataWarehouseSavedQueryMapById
                    ),
                ]
            },
        ],
        treeDataFinal: [
            (s) => [s.treeData, s.searchTreeData, s.searchTerm],
            (treeData, searchTreeData, searchTerm): TreeDataItem[] => {
                if (searchTerm) {
                    return searchTreeData
                }
                return treeData
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

                // Check if this is a file folder that needs loading
                if (folderId.startsWith('file-')) {
                    // Find the folder record in the tree data
                    const findFolderInTree = (items: TreeDataItem[]): TreeDataItem | null => {
                        for (const item of items) {
                            if (item.id === folderId) {
                                return item
                            }
                            if (item.children) {
                                const found = findFolderInTree(item.children)
                                if (found) {
                                    return found
                                }
                            }
                        }
                        return null
                    }

                    const folderRecord = findFolderInTree(values.treeData)

                    if (folderRecord?.record?.type === 'folder' && folderRecord.record.path) {
                        const folderPath = folderRecord.record.path
                        const folderState = values.folderStates[folderPath]

                        // Automatically load the folder if it hasn't been loaded yet
                        if (folderState !== 'loaded' && folderState !== 'loading') {
                            actions.loadFolder(folderPath)
                        }
                    }
                }
            }
        },
        selectSourceTable: ({ tableName }) => {
            // Connect to viewLinkLogic actions
            viewLinkLogic.actions.selectSourceTable(tableName)
            viewLinkLogic.actions.toggleJoinTableModal()
        },
        rename: ({ value, item }) => {
            if (value && value !== item.path.split('/').pop()) {
                const pathParts = item.path.split('/')
                pathParts.pop() // Remove current name
                const newPath = [...pathParts, value].join('/')
                actions.moveItem(item, newPath, false, 'query-database')
            }
            actions.setEditingItemId('')
        },
        addFolder: () => {
            const basePath = UNFILED_SAVED_QUERIES_PATH + '/'
            let folderName = 'Untitled'
            let counter = 2
            while (values.viableItems.find((item) => item.path === basePath + folderName && item.type === 'folder')) {
                folderName = `${folderName} ${counter}`
                counter++
            }

            actions.queueAction(
                {
                    type: 'create',
                    item: { id: `file-${folderName}`, path: basePath + folderName, type: 'folder' },
                    path: basePath + folderName,
                    newPath: basePath + folderName,
                },
                'query-database'
            )

            // Always set the editing item ID after a short delay to ensure the folder is in the DOM
            setTimeout(() => {
                actions.setEditingItemId(`file-${folderName}`)
            }, 50)
        },
        createDataWarehouseSavedQuerySuccess: () => {
            actions.loadFolder(UNFILED_SAVED_QUERIES_PATH, true)
        },
    })),
    subscriptions(({ actions }) => ({
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
        allUnfiledFiles: (allUnfiledFiles: FileSystemEntry[]) => {
            filesFuse.setCollection(allUnfiledFiles)
        },
        unfiledFolders: (unfiledFolders: FileSystemEntry[]) => {
            unfiledFolders.forEach((folder) => {
                actions.loadFolder(folder.path)
            })
        },
    })),
    afterMount(({ actions }) => {
        // Load the unfiled folder on mount to show files
        actions.loadFolder(UNFILED_SAVED_QUERIES_PATH)
    }),
])

export { UNFILED_SAVED_QUERIES_PATH }
