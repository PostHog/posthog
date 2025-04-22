import { IconPlus } from '@posthog/icons'
import { lemonToast, Spinner } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { TreeDataItem, TreeTableViewKeys } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { groupsModel } from '~/models/groupsModel'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'
import { ProjectTreeRef } from '~/types'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { getDefaultTreeExplore, getDefaultTreeNew } from './defaultTree'
import type { projectTreeLogicType } from './projectTreeLogicType'
import { FolderState, ProjectTreeAction } from './types'
import { convertFileSystemEntryToTreeDataItem, findInProjectTree, joinPath, splitPath } from './utils'

const PAGINATION_LIMIT = 100
const MOVE_ALERT_LIMIT = 50
const DELETE_ALERT_LIMIT = 0

export const projectTreeLogic = kea<projectTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'projectTreeLogic']),
    connect(() => ({
        values: [
            groupsModel,
            ['aggregationLabel', 'groupTypes', 'groupsAccessStatus'],
            featureFlagLogic,
            ['featureFlags'],
            panelLayoutLogic,
            ['searchTerm'],
            breadcrumbsLogic,
            ['projectTreeRef'],
        ],
        actions: [panelLayoutLogic, ['setSearchTerm']],
    })),
    actions({
        loadUnfiledItems: true,
        addFolder: (folder: string) => ({ folder }),
        deleteItem: (item: FileSystemEntry) => ({ item }),
        moveItem: (item: FileSystemEntry, newPath: string, force = false) => ({ item, newPath, force }),
        movedItem: (item: FileSystemEntry, oldPath: string, newPath: string) => ({ item, oldPath, newPath }),
        linkItem: (oldPath: string, newPath: string, force = false) => ({ oldPath, newPath, force }),
        queueAction: (action: ProjectTreeAction) => ({ action }),
        removeQueuedAction: (action: ProjectTreeAction) => ({ action }),
        createSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        updateSavedItem: (savedItem: FileSystemEntry, oldPath: string) => ({ savedItem, oldPath }),
        deleteSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        setExpandedFolders: (folderIds: string[]) => ({ folderIds }),
        setExpandedSearchFolders: (folderIds: string[]) => ({ folderIds }),
        setLastViewedId: (id: string) => ({ id }),
        toggleFolderOpen: (folderId: string, isExpanded: boolean) => ({ folderId, isExpanded }),
        setHelpNoticeVisibility: (visible: boolean) => ({ visible }),
        loadFolder: (folder: string) => ({ folder }),
        loadFolderStart: (folder: string) => ({ folder }),
        loadFolderSuccess: (folder: string, entries: FileSystemEntry[], hasMore: boolean, offsetIncrease: number) => ({
            folder,
            entries,
            hasMore,
            offsetIncrease,
        }),
        loadFolderFailure: (folder: string, error: string) => ({ folder, error }),
        rename: (item: FileSystemEntry) => ({ item }),
        createFolder: (parentPath: string) => ({ parentPath }),
        loadSearchResults: (searchTerm: string, offset = 0) => ({ searchTerm, offset }),
        assureVisibility: (projectTreeRef: ProjectTreeRef) => ({ projectTreeRef }),
        setLastNewOperation: (objectType: string | null, folder: string | null) => ({ objectType, folder }),
        onItemChecked: (id: string, checked: boolean) => ({ id, checked }),
        setCheckedItems: (checkedItems: Record<string, boolean>) => ({ checkedItems }),
        expandProjectFolder: (path: string) => ({ path }),
        moveCheckedItems: (path: string) => ({ path }),
        linkCheckedItems: (path: string) => ({ path }),
        deleteCheckedItems: true,
        checkSelectedFolders: true,
        syncTypeAndRef: (type: string, ref: string) => ({ type, ref }),
        updateSyncedFiles: (files: FileSystemEntry[]) => ({ files }),
    }),
    loaders(({ actions, values }) => ({
        unfiledItems: [
            false as boolean,
            {
                loadUnfiledItems: async () => {
                    const response = await api.fileSystem.unfiled()
                    if (response.results.length > 0) {
                        actions.loadFolder('Unfiled')
                        for (const folder of Object.keys(values.folders)) {
                            if (folder.startsWith('Unfiled/')) {
                                actions.loadFolder(folder)
                            }
                        }
                    }
                    return true
                },
            },
        ],
        searchResults: [
            { searchTerm: '', results: [], hasMore: false, lastCount: 0 } as {
                searchTerm: string
                results: FileSystemEntry[]
                hasMore: boolean
                lastCount: number
            },
            {
                loadSearchResults: async ({ searchTerm, offset }, breakpoint) => {
                    await breakpoint(250)
                    const response = await api.fileSystem.list({
                        search: searchTerm,
                        offset,
                        limit: PAGINATION_LIMIT + 1,
                    })
                    breakpoint()

                    return {
                        searchTerm,
                        results: [
                            ...(offset > 0 && searchTerm === values.searchResults.searchTerm
                                ? values.searchResults.results
                                : []),
                            ...response.results.slice(0, PAGINATION_LIMIT),
                        ],
                        hasMore: response.results.length > PAGINATION_LIMIT,
                        lastCount: Math.min(response.results.length, PAGINATION_LIMIT),
                    }
                },
            },
        ],
        pendingLoader: [
            false,
            {
                queueAction: async ({ action }) => {
                    if ((action.type === 'prepare-move' || action.type === 'prepare-link') && action.newPath) {
                        const verb = action.type === 'prepare-link' ? 'link' : 'move'
                        const verbing = action.type === 'prepare-link' ? 'linking' : 'moving'
                        try {
                            const response = await api.fileSystem.count(action.item.id)
                            actions.removeQueuedAction(action)
                            if (response && response.count > MOVE_ALERT_LIMIT) {
                                const confirmMessage = `You're about to ${verb} ${response.count} items. Are you sure?`
                                if (!confirm(confirmMessage)) {
                                    return false
                                }
                            }
                            actions.queueAction({ ...action, type: verb })
                        } catch (error) {
                            console.error(`Error ${verbing} item:`, error)
                            lemonToast.error(`Error ${verbing} item: ${error}`)
                            actions.removeQueuedAction(action)
                        }
                    } else if (action.type === 'move' && action.newPath) {
                        try {
                            const oldPath = action.item.path
                            const newPath = action.newPath
                            await api.fileSystem.move(action.item.id, newPath)
                            actions.removeQueuedAction(action)
                            actions.movedItem(action.item, oldPath, newPath)
                            lemonToast.success('Item moved successfully', {
                                button: {
                                    label: 'Undo',
                                    dataAttr: 'undo-project-tree-move',
                                    action: () => {
                                        actions.moveItem({ ...action.item, path: newPath }, oldPath)
                                    },
                                },
                            })
                        } catch (error) {
                            console.error('Error moving item:', error)
                            lemonToast.error(`Error moving item: ${error}`)
                            actions.removeQueuedAction(action)
                        }
                    } else if (action.type === 'link' && action.newPath) {
                        try {
                            const newPath = action.newPath
                            const newItem = await api.fileSystem.link(action.item.id, newPath)
                            actions.removeQueuedAction(action)
                            if (newItem) {
                                actions.createSavedItem(newItem)
                            }
                            if (action.item.type === 'folder') {
                                actions.loadFolder(newPath)
                            }
                            lemonToast.success('Item linked successfully') // TODO: undo for linking
                        } catch (error) {
                            console.error('Error linking item:', error)
                            lemonToast.error(`Error linking item: ${error}`)
                            actions.removeQueuedAction(action)
                        }
                    } else if (action.type === 'create') {
                        try {
                            const response = await api.fileSystem.create(action.item)
                            actions.removeQueuedAction(action)
                            actions.createSavedItem(response)
                            lemonToast.success('Folder created successfully', {
                                button: {
                                    label: 'Undo',
                                    dataAttr: 'undo-project-tree-create-folder',
                                    action: () => {
                                        actions.deleteItem(response)
                                    },
                                },
                            })
                            actions.expandProjectFolder(action.item.path)
                        } catch (error) {
                            console.error('Error creating folder:', error)
                            lemonToast.error(`Error creating folder: ${error}`)
                            actions.removeQueuedAction(action)
                        }
                    } else if (action.type === 'prepare-delete' && action.item.id) {
                        try {
                            const response = await api.fileSystem.count(action.item.id)
                            actions.removeQueuedAction(action)
                            if (response && response.count > DELETE_ALERT_LIMIT) {
                                const confirmMessage = `You're about to move ${response.count} items into 'Unfiled'. Are you sure?`
                                if (!confirm(confirmMessage)) {
                                    return false
                                }
                            }
                            actions.queueAction({ ...action, type: 'delete' })
                        } catch (error) {
                            console.error('Error deleting item:', error)
                            lemonToast.error(`Error deleting item: ${error}`)
                            actions.removeQueuedAction(action)
                        }
                    } else if (action.type === 'delete' && action.item.id) {
                        try {
                            await api.fileSystem.delete(action.item.id)
                            actions.removeQueuedAction(action)
                            actions.deleteSavedItem(action.item)
                            lemonToast.success('Item deleted successfully')
                        } catch (error) {
                            console.error('Error deleting item:', error)
                            lemonToast.error(`Error deleting item: ${error}`)
                            actions.removeQueuedAction(action)
                        }
                    }
                    return true
                },
            },
        ],
    })),
    reducers({
        folders: [
            {} as Record<string, FileSystemEntry[]>,
            {
                loadFolderSuccess: (state, { folder, entries }) => ({ ...state, [folder]: entries }),
                createSavedItem: (state, { savedItem }) => {
                    const folder = joinPath(splitPath(savedItem.path).slice(0, -1))
                    return { ...state, [folder]: [...(state[folder] || []), savedItem] }
                },
                loadSearchResultsSuccess: (state, { searchResults }) => {
                    // Append search results into the loaded state to persist data and help with multi-selection between panels
                    const { results, lastCount } = searchResults
                    const newState: Record<string, FileSystemEntry[]> = { ...state }
                    for (const result of results.slice(-1 * lastCount)) {
                        const folder = joinPath(splitPath(result.path).slice(0, -1))
                        if (newState[folder]) {
                            newState[folder] = [...newState[folder], result]
                        } else {
                            newState[folder] = [result]
                        }
                    }
                    return newState
                },
                updateSavedItem: (state, { savedItem, oldPath }) => {
                    const oldFolder = joinPath(splitPath(oldPath).slice(0, -1))
                    const folder = joinPath(splitPath(savedItem.path).slice(0, -1))

                    if (oldFolder === folder) {
                        return {
                            ...state,
                            [folder]: (state[folder] ?? []).map((item) =>
                                item.id === savedItem.id ? savedItem : item
                            ),
                        }
                    }
                    return {
                        ...state,
                        [oldFolder]: (state[oldFolder] ?? []).filter((item) => item.id !== savedItem.id),
                        [folder]: [...(state[folder] ?? []), savedItem],
                    }
                },
                deleteSavedItem: (state, { savedItem }) => {
                    const folder = joinPath(splitPath(savedItem.path).slice(0, -1))
                    const newState = {
                        ...state,
                        [folder]: state[folder].filter((item) => item.id !== savedItem.id),
                    }
                    if (savedItem.type === 'folder') {
                        for (const folder of Object.keys(newState)) {
                            if (folder === savedItem.path || folder.startsWith(savedItem.path + '/')) {
                                delete newState[folder]
                            }
                        }
                    }
                    return newState
                },
                movedItem: (state, { oldPath, newPath, item }) => {
                    const newState = { ...state }
                    const oldParentFolder = joinPath(splitPath(oldPath).slice(0, -1))
                    for (const folder of Object.keys(newState)) {
                        if (folder === oldParentFolder) {
                            newState[folder] = newState[folder].filter((i) => i.id !== item.id)
                            const newParentFolder = joinPath(splitPath(newPath).slice(0, -1))
                            newState[newParentFolder] = [
                                ...(newState[newParentFolder] ?? []),
                                { ...item, path: newPath },
                            ]
                        } else if (folder === oldPath || folder.startsWith(oldPath + '/')) {
                            const newFolder = newPath + folder.slice(oldPath.length)
                            newState[newFolder] = [
                                ...(newState[newFolder] ?? []),
                                ...newState[folder].map((item) => ({
                                    ...item,
                                    path: newFolder + item.path.slice(folder.length),
                                })),
                            ]
                            delete newState[folder]
                        }
                    }
                    return newState
                },
                updateSyncedFiles: (state, { files }) => {
                    const filesById: Record<string, FileSystemEntry> = {}
                    for (const file of files) {
                        filesById[file.id] = file
                    }
                    const newState = { ...state }
                    for (const [folder, filesInFolder] of Object.entries(newState)) {
                        if (filesInFolder.find((file) => filesById[file.id])) {
                            newState[folder] = newState[folder].map((f) => filesById[f.id] ?? f)
                        }
                    }
                    return newState
                },
            },
        ],
        folderLoadOffset: [
            {} as Record<string, number>,
            {
                loadFolderSuccess: (state, { folder, offsetIncrease }) => {
                    return { ...state, [folder]: offsetIncrease + (state[folder] ?? 0) }
                },
            },
        ],
        folderStates: [
            {} as Record<string, FolderState>,
            {
                loadFolderStart: (state, { folder }) => ({ ...state, [folder]: 'loading' }),
                loadFolderSuccess: (state, { folder, hasMore }) => ({
                    ...state,
                    [folder]: hasMore ? 'has-more' : 'loaded',
                }),
                loadFolderFailure: (state, { folder }) => ({ ...state, [folder]: 'error' }),
            },
        ],
        lastNewOperation: [
            null as { objectType: string; folder: string } | null,
            {
                setLastNewOperation: (_, { folder, objectType }) => {
                    if (folder && objectType) {
                        return { folder, objectType }
                    }
                    return null
                },
            },
        ],
        pendingActions: [
            [] as ProjectTreeAction[],
            {
                queueAction: (state, { action }) => [...state, action],
                removeQueuedAction: (state, { action }) => state.filter((a) => a !== action),
            },
        ],
        expandedFolders: [
            [] as string[],
            {
                setExpandedFolders: (_, { folderIds }) => folderIds,
            },
        ],
        expandedSearchFolders: [
            ['project-folder/Unfiled'] as string[],
            {
                setExpandedSearchFolders: (_, { folderIds }) => folderIds,
                loadSearchResultsSuccess: (state, { searchResults: { results, lastCount } }) => {
                    const folders: Record<string, boolean> = state.reduce(
                        (acc: Record<string, boolean>, folderId) => {
                            acc[folderId] = true
                            return acc
                        },
                        { 'project-folder/Unfiled': true }
                    )

                    for (const entry of results.slice(-lastCount)) {
                        const splits = splitPath(entry.path)
                        for (let i = 1; i < splits.length; i++) {
                            folders['project-folder/' + joinPath(splits.slice(0, i))] = true
                        }
                    }
                    return Object.keys(folders)
                },
            },
        ],
        lastViewedId: [
            '',
            {
                setLastViewedId: (_, { id }) => id,
            },
        ],
        helpNoticeVisible: [
            true,
            {
                setHelpNoticeVisibility: (_, { visible }) => visible,
            },
        ],
        checkedItems: [
            {} as Record<string, boolean>,
            {
                setCheckedItems: (_, { checkedItems }) => checkedItems,
            },
        ],
    }),
    selectors({
        savedItems: [
            (s) => [s.folders, s.folderStates],
            (folders): FileSystemEntry[] =>
                Object.entries(folders).reduce((acc, [_, items]) => [...acc, ...items], [] as FileSystemEntry[]),
        ],
        savedItemsLoading: [
            (s) => [s.folderStates],
            (folderStates): boolean => Object.values(folderStates).some((state) => state === 'loading'),
        ],
        viableItems: [
            // Combine savedItems with pendingActions
            (s) => [s.savedItems, s.pendingActions],
            (savedItems, pendingActions): FileSystemEntry[] => {
                const initialItems = [...savedItems]
                const itemsByPath = initialItems.reduce((acc, item) => {
                    acc[item.path] = acc[item.path] ? [...acc[item.path], item] : [item]
                    return acc
                }, {} as Record<string, FileSystemEntry[]>)

                for (const action of pendingActions) {
                    if ((action.type === 'move' || action.type === 'prepare-move') && action.newPath) {
                        if (!itemsByPath[action.path] || itemsByPath[action.path].length === 0) {
                            console.error("Item not found, can't move", action.path)
                            continue
                        }
                        for (const item of itemsByPath[action.path]) {
                            const itemTarget = itemsByPath[action.newPath]?.[0]
                            if (item.type === 'folder') {
                                if (!itemTarget || itemTarget.type === 'folder') {
                                    for (const path of Object.keys(itemsByPath)) {
                                        if (path.startsWith(action.path + '/')) {
                                            for (const loopItem of itemsByPath[path]) {
                                                const newPath = action.newPath + loopItem.path.slice(action.path.length)
                                                if (!itemsByPath[newPath]) {
                                                    itemsByPath[newPath] = []
                                                }
                                                itemsByPath[newPath] = [
                                                    ...itemsByPath[newPath],
                                                    { ...loopItem, path: newPath, _loading: true },
                                                ]
                                            }
                                            delete itemsByPath[path]
                                        }
                                    }
                                }
                                if (!itemTarget) {
                                    itemsByPath[action.newPath] = [
                                        ...(itemsByPath[action.newPath] ?? []),
                                        { ...item, path: action.newPath, _loading: true },
                                    ]
                                }
                                delete itemsByPath[action.path]
                            } else if (item.id === action.item.id) {
                                if (!itemsByPath[action.newPath]) {
                                    itemsByPath[action.newPath] = []
                                }
                                itemsByPath[action.newPath] = [
                                    ...itemsByPath[action.newPath],
                                    { ...item, path: action.newPath, _loading: true },
                                ]
                                if (itemsByPath[action.path].length > 1) {
                                    itemsByPath[action.path] = itemsByPath[action.path].filter((i) => i.id !== item.id)
                                } else {
                                    delete itemsByPath[action.path]
                                }
                            }
                        }
                    } else if (action.type === 'create' && action.newPath) {
                        if (!itemsByPath[action.newPath]) {
                            itemsByPath[action.newPath] = [
                                ...(itemsByPath[action.newPath] ?? []),
                                { ...action.item, path: action.newPath, _loading: true },
                            ]
                        } else {
                            console.error("Item already exists, can't create", action.item)
                        }
                    } else if (action.path && itemsByPath[action.path]) {
                        itemsByPath[action.path] = itemsByPath[action.path].map((i) => ({ ...i, loading: true }))
                    }
                }
                return Object.values(itemsByPath).flatMap((a) => a)
            },
        ],
        sortedItems: [
            (s) => [s.viableItems],
            (viableItems): FileSystemEntry[] =>
                [...viableItems].sort((a, b) => (a.path > b.path ? 1 : a.path < b.path ? -1 : 0)),
        ],
        viableItemsById: [
            (s) => [s.viableItems],
            (viableItems): Record<string, FileSystemEntry> =>
                viableItems.reduce(
                    (acc, item) => ({
                        ...acc,
                        [item.type === 'folder' ? 'project-folder/' + item.path : 'project/' + item.id]: item,
                    }),
                    {} as Record<string, FileSystemEntry>
                ),
        ],
        unappliedPaths: [
            // Paths that are currently being loaded
            (s) => [s.pendingActions],
            (pendingActions) => {
                const unappliedPaths: Record<string, boolean> = {}
                for (const action of pendingActions) {
                    if (action.type === 'move' || action.type === 'create') {
                        if (action.newPath) {
                            unappliedPaths[action.newPath] = true
                            const split = splitPath(action.newPath)
                            for (let i = 1; i < split.length; i++) {
                                unappliedPaths[joinPath(split.slice(0, i))] = true
                            }
                        }
                    }
                }
                return unappliedPaths
            },
        ],
        loadingPaths: [
            // Paths that are currently being loaded
            (s) => [s.unfiledItemsLoading, s.savedItemsLoading, s.pendingLoaderLoading, s.pendingActions],
            (unfiledItemsLoading, savedItemsLoading, pendingLoaderLoading, pendingActions) => {
                const loadingPaths: Record<string, boolean> = {}
                if (unfiledItemsLoading) {
                    loadingPaths['Unfiled'] = true
                    loadingPaths[''] = true
                }
                if (savedItemsLoading) {
                    loadingPaths[''] = true
                }
                if (pendingLoaderLoading && pendingActions.length > 0) {
                    loadingPaths[pendingActions[0].newPath || pendingActions[0].path] = true
                }
                return loadingPaths
            },
        ],
        pendingActionsCount: [(s) => [s.pendingActions], (pendingActions): number => pendingActions.length],
        projectTree: [
            (s) => [s.viableItems, s.folderStates, s.checkedItems],
            (viableItems, folderStates, checkedItems): TreeDataItem[] =>
                convertFileSystemEntryToTreeDataItem({
                    imports: viableItems,
                    folderStates,
                    checkedItems,
                    root: 'project',
                }),
        ],
        groupNodes: [
            (s) => [s.groupTypes, s.groupsAccessStatus, s.aggregationLabel],
            (groupTypes, groupsAccessStatus, aggregationLabel): FileSystemImport[] => {
                const showGroupsIntroductionPage = [
                    GroupsAccessStatus.HasAccess,
                    GroupsAccessStatus.HasGroupTypes,
                    GroupsAccessStatus.NoAccess,
                ].includes(groupsAccessStatus)

                const groupNodes: FileSystemImport[] = [
                    ...(showGroupsIntroductionPage
                        ? [
                              {
                                  path: 'Groups',
                                  href: () => urls.groups(0),
                              },
                          ]
                        : Array.from(groupTypes.values()).map((groupType) => ({
                              path: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                              href: () => urls.groups(groupType.group_type_index),
                          }))),
                ]

                return groupNodes
            },
        ],
        treeItemsNew: [
            (s) => [s.featureFlags, s.folderStates],
            (featureFlags, folderStates): TreeDataItem[] =>
                convertFileSystemEntryToTreeDataItem({
                    imports: getDefaultTreeNew().filter((f) => !f.flag || featureFlags[f.flag]),
                    checkedItems: {},
                    folderStates,
                    root: 'new',
                }),
        ],
        treeItemsNewByNestedProduct: [
            (s) => [s.treeItemsNew],
            (treeItemsNew): TreeDataItem[] => {
                // Create arrays for each category
                const dataItems = treeItemsNew
                    .filter((item: TreeDataItem) => item.record?.type.includes('hog_function/'))
                    .sort((a: TreeDataItem, b: TreeDataItem) => a.name.localeCompare(b.name))

                const insightItems = treeItemsNew
                    .filter((item: TreeDataItem) => item.record?.type === 'insight')
                    .sort((a: TreeDataItem, b: TreeDataItem) => a.name.localeCompare(b.name))

                // Get other items (not data or insight)
                const otherItems = treeItemsNew
                    .filter(
                        (item: TreeDataItem) =>
                            !item.record?.type.includes('hog_function/') && !item.record?.type.includes('insight')
                    )
                    .sort((a: TreeDataItem, b: TreeDataItem) => a.name.localeCompare(b.name))

                // Create the final hierarchical structure with explicit names for grouped items
                const result = [
                    ...otherItems,
                    { id: 'data', name: 'Data', children: dataItems },
                    { id: 'insight', name: 'Insight', children: insightItems },
                ]

                // Sort the top level alphabetically (keeping the structure)
                return result.sort((a: TreeDataItem, b: TreeDataItem) => {
                    // Always use name for sorting (with fallback to id)
                    const nameA = a.name || a.id.charAt(0).toUpperCase() + a.id.slice(1)
                    const nameB = b.name || b.id.charAt(0).toUpperCase() + b.id.slice(1)
                    return nameA.localeCompare(nameB)
                })
            },
        ],
        treeItemsExplore: [
            (s) => [s.featureFlags, s.groupNodes, s.folderStates],
            (featureFlags, groupNodes: FileSystemImport[], folderStates): TreeDataItem[] =>
                convertFileSystemEntryToTreeDataItem({
                    imports: getDefaultTreeExplore(groupNodes).filter((f) => !f.flag || featureFlags[f.flag]),
                    checkedItems: {},
                    folderStates,
                    root: 'explore',
                }),
        ],
        searchedTreeItems: [
            (s) => [s.searchResults, s.searchResultsLoading, s.folderStates, s.checkedItems],
            (searchResults, searchResultsLoading, folderStates, checkedItems): TreeDataItem[] => {
                const results = convertFileSystemEntryToTreeDataItem({
                    imports: searchResults.results,
                    folderStates,
                    checkedItems,
                    root: 'project',
                    searchTerm: searchResults.searchTerm,
                    disableFolderSelect: true,
                })
                if (searchResults.hasMore) {
                    if (searchResultsLoading) {
                        results.push({
                            id: `search-loading/`,
                            name: 'Loading...',
                            icon: <Spinner />,
                        })
                    } else {
                        results.push({
                            id: `search-load-more/${searchResults.searchTerm}`,
                            name: 'Load more...',
                            icon: <IconPlus />,
                            onClick: () =>
                                projectTreeLogic.actions.loadSearchResults(
                                    searchResults.searchTerm,
                                    searchResults.results.length
                                ),
                        })
                    }
                }
                return results
            },
        ],
        treeData: [
            (s) => [s.searchTerm, s.searchedTreeItems, s.projectTree, s.loadingPaths, s.searchResultsLoading],
            (searchTerm, searchedTreeItems, projectTree, loadingPaths, searchResultsLoading): TreeDataItem[] => {
                if (searchTerm) {
                    if (searchResultsLoading && searchedTreeItems.length === 0) {
                        return [
                            {
                                id: `search-loading/`,
                                name: 'Loading...',
                                icon: <Spinner />,
                            },
                        ]
                    }
                    return searchedTreeItems
                }
                if (loadingPaths[''] && projectTree.length === 0) {
                    return [
                        {
                            id: `folder-loading/`,
                            name: 'Loading...',
                            icon: <Spinner />,
                        },
                    ]
                }
                return projectTree
            },
        ],
        // TODO: use treeData + some other logic to determine the keys
        treeTableKeys: [
            () => [],
            (): TreeTableViewKeys => ({
                headers: [
                    {
                        key: 'name',
                        title: 'Name',
                        tooltip: (value: string) => value,
                    },
                    {
                        key: 'record.created_at',
                        title: 'Created at',
                        formatFunction: (value: string) => dayjs(value).format('MMM D, YYYY'),
                        tooltip: (value: string) => dayjs(value).format('MMM D, YYYY HH:mm:ss'),
                    },
                    {
                        key: 'record.created_by.first_name',
                        title: 'Created by',
                        tooltip: (value: string) => value,
                    },
                ],
            }),
        ],
        checkedItemCountNumeric: [
            (s) => [s.checkedItems],
            (checkedItems): number => Object.values(checkedItems).filter((v) => !!v).length,
        ],
        checkedItemsCount: [
            (s) => [s.checkedItems, s.viableItemsById],
            (checkedItems, viableItemsById): string => {
                let hasFolder = false
                let sum = 0
                for (const [key, value] of Object.entries(checkedItems)) {
                    if (value) {
                        sum += 1
                        if (viableItemsById[key]?.type === 'folder') {
                            hasFolder = true
                        }
                    }
                }

                return `${sum}${hasFolder ? '+' : ''}`
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadFolder: async ({ folder }) => {
            const currentState = values.folderStates[folder]
            if (currentState === 'loading' || currentState === 'loaded') {
                return
            }
            actions.loadFolderStart(folder)
            try {
                const previousFiles = values.folders[folder] || []
                const offset = values.folderLoadOffset[folder] ?? 0
                const response = await api.fileSystem.list({
                    parent: folder,
                    depth: splitPath(folder).length + 1,
                    limit: PAGINATION_LIMIT + 1,
                    offset: offset,
                })

                let files = response.results
                let hasMore = false
                if (files.length > PAGINATION_LIMIT) {
                    files = files.slice(0, PAGINATION_LIMIT)
                    hasMore = true
                }
                const fileIds = new Set(files.map((file) => file.id))
                const previousUniqueFiles = previousFiles.filter(
                    (prevFile) => !fileIds.has(prevFile.id) && prevFile.path !== folder
                )
                actions.loadFolderSuccess(folder, [...previousUniqueFiles, ...files], hasMore, files.length)
            } catch (error) {
                actions.loadFolderFailure(folder, String(error))
            }
        },
        loadFolderSuccess: ({ folder }) => {
            if (folder === '') {
                const rootItems = values.folders['']
                if (rootItems.length < 5) {
                    actions.toggleFolderOpen('project-folder/Unfiled', true)
                }
            }
            actions.checkSelectedFolders()
        },
        createSavedItem: () => {
            actions.checkSelectedFolders()
        },
        loadSearchResultsSuccess: () => {
            actions.checkSelectedFolders()
        },
        updateSavedItem: () => {
            actions.checkSelectedFolders()
        },
        deleteSavedItem: () => {
            actions.checkSelectedFolders()
        },
        movedItem: () => {
            actions.checkSelectedFolders()
        },
        linkedItem: () => {
            actions.checkSelectedFolders()
        },
        checkSelectedFolders: () => {
            // Select items added into folders that are selected
            const checkedItems = values.checkedItems
            const toCheck = []
            let checkingFolder: string | null = null
            for (const item of values.sortedItems) {
                if (checkingFolder === null) {
                    if (item.type === 'folder' && checkedItems[`project-folder/${item.path}`]) {
                        checkingFolder = item.path
                    }
                } else {
                    if (item.path.startsWith(checkingFolder + '/')) {
                        if (item.type === 'folder') {
                            if (!checkedItems[`project-folder/${item.path}`]) {
                                toCheck.push(`project-folder/${item.path}`)
                            }
                        } else {
                            if (!checkedItems[`project/${item.id}`]) {
                                toCheck.push(`project/${item.id}`)
                            }
                        }
                    } else {
                        checkingFolder = null
                    }
                }
            }
            const toDelete = new Set<string>()
            for (const itemId of Object.keys(checkedItems)) {
                if (!values.viableItemsById[itemId]) {
                    toDelete.add(itemId)
                }
            }
            if (toCheck.length > 0 || toDelete.size > 0) {
                actions.setCheckedItems({
                    ...(toDelete.size === 0
                        ? checkedItems
                        : Object.fromEntries(Object.entries(checkedItems).filter((kv) => !toDelete.has(kv[0])))),
                    ...Object.fromEntries(toCheck.map((item) => [item, true])),
                })
            }
        },
        expandProjectFolder: ({ path }) => {
            const expandedSet = new Set(values.expandedFolders)
            const allFolders = splitPath(path).slice(0, -1)
            const allFullFolders = allFolders.map((_, index) => joinPath(allFolders.slice(0, index + 1)))
            const nonExpandedFolders = allFullFolders.filter((f) => !expandedSet.has('project-folder/' + f))
            for (const folder of nonExpandedFolders) {
                if (values.folderStates[folder] !== 'loaded' && values.folderStates[folder] !== 'loading') {
                    actions.loadFolder(folder)
                }
            }
            actions.setExpandedFolders([
                ...values.expandedFolders,
                ...nonExpandedFolders.map((f) => 'project-folder/' + f),
            ])
        },
        onItemChecked: ({ id, checked }) => {
            const sortedItems: FileSystemEntry[] = values.sortedItems
            const clickedItem: FileSystemEntry | undefined = values.viableItemsById[id]
            if (!clickedItem) {
                return
            }
            const checkedItems = { ...values.checkedItems }
            if (clickedItem.type === 'folder') {
                const itemIndex = sortedItems.findIndex((i) => i.id === clickedItem.id)
                for (let i = itemIndex; i < sortedItems.length; i++) {
                    const item = sortedItems[i]
                    if (item.path !== clickedItem.path && !item.path.startsWith(clickedItem.path + '/')) {
                        break
                    }
                    const itemId = item.type === 'folder' ? `project-folder/${item.path}` : `project/${item.id}`
                    if (checked) {
                        checkedItems[itemId] = true
                    } else {
                        checkedItems[itemId] = false
                    }
                }
            } else {
                checkedItems[`project/${clickedItem.id}`] = !!checked
            }
            actions.setCheckedItems(checkedItems)
        },
        moveCheckedItems: ({ path }) => {
            const { checkedItems } = values
            let skipInFolder: string | null = null
            for (const item of values.sortedItems) {
                if (skipInFolder !== null) {
                    if (item.path.startsWith(skipInFolder + '/')) {
                        continue
                    } else {
                        skipInFolder = null
                    }
                }
                const itemId = item.type === 'folder' ? `project-folder/${item.path}` : `project/${item.id}`
                if (checkedItems[itemId]) {
                    actions.moveItem(item, joinPath([...splitPath(path), ...splitPath(item.path).slice(-1)]), true)
                    if (item.type === 'folder') {
                        skipInFolder = item.path
                    }
                }
            }
        },
        moveItem: async ({ item, newPath, force }) => {
            if (newPath === item.path) {
                return
            }
            if (!item.id) {
                lemonToast.error("Sorry, can't move an unsaved item (no id)")
                return
            }
            actions.queueAction({
                type: !force && item.type === 'folder' ? 'prepare-move' : 'move',
                item,
                path: item.path,
                newPath: newPath,
            })
        },
        linkCheckedItems: ({ path }) => {
            const { checkedItems } = values
            let skipInFolder: string | null = null
            for (const item of values.sortedItems) {
                if (skipInFolder !== null) {
                    if (item.path.startsWith(skipInFolder + '/')) {
                        continue
                    } else {
                        skipInFolder = null
                    }
                }
                const itemId = item.type === 'folder' ? `project-folder/${item.path}` : `project/${item.id}`
                if (checkedItems[itemId]) {
                    actions.linkItem(item.path, joinPath([...splitPath(path), ...splitPath(item.path).slice(-1)]), true)
                    if (item.type === 'folder') {
                        skipInFolder = item.path
                    }
                }
            }
        },
        linkItem: async ({ oldPath, newPath, force }) => {
            if (newPath === oldPath) {
                lemonToast.error('Cannot link folder into itself')
                return
            }
            const item = values.viableItems.find((item) => item.path === oldPath)
            if (item && item.path === oldPath) {
                if (!item.id) {
                    lemonToast.error("Sorry, can't link an unsaved item (no id)")
                    return
                }
                actions.queueAction({
                    type: !force && item.type === 'folder' ? 'prepare-link' : 'link',
                    item,
                    path: item.path,
                    newPath: newPath + item.path.slice(oldPath.length),
                })
            }
        },
        deleteCheckedItems: () => {
            const { checkedItems } = values
            let skipInFolder: string | null = null
            for (const item of values.sortedItems) {
                if (skipInFolder !== null) {
                    if (item.path.startsWith(skipInFolder + '/')) {
                        continue
                    } else {
                        skipInFolder = null
                    }
                }
                const itemId = item.type === 'folder' ? `project-folder/${item.path}` : `project/${item.id}`
                if (checkedItems[itemId]) {
                    actions.deleteItem(item)
                    if (item.type === 'folder') {
                        skipInFolder = item.path
                    }
                }
            }
        },
        deleteItem: async ({ item }) => {
            if (!item.id) {
                const response = await api.fileSystem.list({ type: 'folder', path: item.path })
                const items = response.results ?? []
                if (items.length > 0) {
                    item = items[0]
                } else {
                    lemonToast.error(`Could not find filesystem entry for ${item.path}. Can't delete.`)
                    return
                }
            }
            actions.queueAction({ type: item.type === 'folder' ? 'prepare-delete' : 'delete', item, path: item.path })
        },
        addFolder: ({ folder }) => {
            if (values.viableItems.find((item) => item.path === folder && item.type === 'folder')) {
                return
            }
            actions.queueAction({
                type: 'create',
                item: { id: `project/${folder}`, path: folder, type: 'folder' },
                path: folder,
                newPath: folder,
            })
        },
        toggleFolderOpen: ({ folderId }) => {
            if (values.searchTerm) {
                if (values.expandedSearchFolders.find((f) => f === folderId)) {
                    actions.setExpandedSearchFolders(values.expandedSearchFolders.filter((f) => f !== folderId))
                } else {
                    actions.setExpandedSearchFolders([...values.expandedSearchFolders, folderId])
                }
            } else {
                if (values.expandedFolders.find((f) => f === folderId)) {
                    actions.setExpandedFolders(values.expandedFolders.filter((f) => f !== folderId))
                } else {
                    actions.setExpandedFolders([...values.expandedFolders, folderId])

                    if (values.folderStates[folderId] !== 'loaded' && values.folderStates[folderId] !== 'loading') {
                        const folder = findInProjectTree(folderId, values.projectTree)
                        folder && actions.loadFolder(folder.record?.path)
                    }
                }
            }
        },
        rename: ({ item }) => {
            const splits = splitPath(item.path)
            if (splits.length > 0) {
                const currentName = splits[splits.length - 1].replace(/\\/g, '')
                const folder = prompt('New name?', currentName)
                if (folder) {
                    actions.moveItem(item, joinPath([...splits.slice(0, -1), folder]))
                }
            }
        },
        createFolder: ({ parentPath }) => {
            const promptMessage = parentPath ? `Create a folder under "${parentPath}":` : 'Create a new folder:'
            const folder = prompt(promptMessage, '')
            if (folder) {
                const parentSplits = parentPath ? splitPath(parentPath) : []
                const newPath = joinPath([...parentSplits, folder])
                actions.addFolder(newPath)
            }
        },
        setSearchTerm: ({ searchTerm }) => {
            actions.loadSearchResults(searchTerm)
        },
        assureVisibility: async ({ projectTreeRef }, breakpoint) => {
            if (projectTreeRef) {
                const treeItem = projectTreeRef.type.endsWith('/')
                    ? values.viableItems.find(
                          (item) => item.type?.startsWith(projectTreeRef.type) && item.ref === projectTreeRef.ref
                      )
                    : values.viableItems.find(
                          (item) => item.type === projectTreeRef.type && item.ref === projectTreeRef.ref
                      )
                let path: string | undefined
                if (treeItem) {
                    path = treeItem.path
                } else {
                    const resp = await api.fileSystem.list(
                        projectTreeRef.type.endsWith('/')
                            ? { ref: projectTreeRef.ref, type__startswith: projectTreeRef.type }
                            : { ref: projectTreeRef.ref, type: projectTreeRef.type }
                    )
                    breakpoint() // bail if we opened some other item in the meanwhile
                    if (resp.results && resp.results.length > 0) {
                        const { lastNewOperation } = values
                        const result = resp.results[0]
                        path = result.path

                        // Check if a "new" action was recently initiated for this object type.
                        // If so, move the item to the new path.
                        // TODO: also check that this was created by you (we need to add the user's uuid to metadata)
                        // - const createdBy = result.meta?.created_by
                        if (
                            result.path.startsWith('Unfiled/') &&
                            lastNewOperation &&
                            (lastNewOperation.objectType === result.type ||
                                (lastNewOperation.objectType.includes('/') &&
                                    result.type?.includes('/') &&
                                    lastNewOperation.objectType.split('/')[0] === result.type.split('/')[0]))
                        ) {
                            const newPath = joinPath([
                                ...splitPath(lastNewOperation.folder),
                                ...splitPath(result.path).slice(-1),
                            ])
                            actions.createSavedItem({ ...result, path: newPath })
                            path = newPath
                            await api.fileSystem.move(result.id, newPath)
                        } else {
                            actions.createSavedItem(result)
                        }
                        if (lastNewOperation) {
                            actions.setLastNewOperation(null, null)
                        }
                    }
                }

                if (path) {
                    actions.expandProjectFolder(path)
                }
            }
        },
        syncTypeAndRef: async ({ type, ref }) => {
            const items = await (type.endsWith('/')
                ? api.fileSystem.list({ type__startswith: type, ref })
                : api.fileSystem.list({ type, ref }))
            actions.updateSyncedFiles(items.results)
        },
    })),
    subscriptions(({ actions }) => ({
        projectTreeRef: (newRef: ProjectTreeRef | null) => {
            if (newRef) {
                actions.assureVisibility(newRef)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadFolder('')
        actions.loadUnfiledItems()
        if (values.projectTreeRef) {
            actions.assureVisibility(values.projectTreeRef)
        }
    }),
])

export function refreshTreeItem(type: string, ref: string): void {
    projectTreeLogic.findMounted()?.actions.syncTypeAndRef(type, ref)
}
