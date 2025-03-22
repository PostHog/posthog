import { IconPlus } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { getDefaultTree } from './defaultTree'
import type { projectTreeLogicType } from './projectTreeLogicType'
import { FolderState, ProjectTreeAction } from './types'
import {
    convertFileSystemEntryToFlatTreeDataItem,
    convertFileSystemEntryToTreeDataItem,
    findInProjectTree,
    joinPath,
    splitPath,
} from './utils'
const PAGINATION_LIMIT = 100

export const projectTreeLogic = kea<projectTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'projectTreeLogic']),
    connect({
        values: [
            groupsModel,
            ['aggregationLabel', 'groupTypes', 'groupsAccessStatus'],
            featureFlagLogic,
            ['featureFlags'],
            panelLayoutLogic,
            ['searchTerm'],
        ],
        actions: [panelLayoutLogic, ['setSearchTerm']],
    }),
    actions({
        loadUnfiledItems: true,
        addFolder: (folder: string) => ({ folder }),
        deleteItem: (item: FileSystemEntry) => ({ item }),
        moveItem: (oldPath: string, newPath: string) => ({ oldPath, newPath }),
        queueAction: (action: ProjectTreeAction) => ({ action }),
        removeQueuedAction: (action: ProjectTreeAction) => ({ action }),
        applyPendingActions: true,
        cancelPendingActions: true,
        createSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        updateSavedItem: (savedItem: FileSystemEntry, oldPath: string) => ({ savedItem, oldPath }),
        deleteSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        setExpandedFolders: (folderIds: string[]) => ({ folderIds }),
        setLastViewedId: (id: string) => ({ id }),
        toggleFolderOpen: (folderId: string, isExpanded: boolean) => ({ folderId, isExpanded }),
        setHelpNoticeVisibility: (visible: boolean) => ({ visible }),
        loadFolder: (folder: string) => ({ folder }),
        loadFolderStart: (folder: string) => ({ folder }),
        loadFolderSuccess: (folder: string, entries: FileSystemEntry[], hasMore: boolean = false) => ({
            folder,
            entries,
            hasMore,
        }),
        loadFolderFailure: (folder: string, error: string) => ({ folder, error }),
        rename: (path: string) => ({ path }),
        createFolder: (parentPath: string) => ({ parentPath }),
        loadSearchResults: (searchTerm: string, offset = 0) => ({ searchTerm, offset }),
    }),
    loaders(({ actions, values }) => ({
        allUnfiledItems: [
            [] as FileSystemEntry[],
            {
                loadUnfiledItems: async () => {
                    const response = await api.fileSystem.unfiled()
                    return [...values.allUnfiledItems, ...response.results]
                },
            },
        ],
        searchResults: [
            { searchTerm: '', results: [], hasMore: false } as {
                searchTerm: string
                results: FileSystemEntry[]
                hasMore: boolean
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
                    }
                },
            },
        ],
        pendingLoader: [
            false,
            {
                applyPendingActions: async () => {
                    for (const action of values.pendingActions) {
                        if (action.type === 'move' && action.newPath) {
                            if (!action.item.id) {
                                const response = await api.fileSystem.create({ ...action.item, path: action.newPath })
                                actions.createSavedItem(response)
                            } else {
                                const response = await api.fileSystem.update(action.item.id, { path: action.newPath })
                                actions.updateSavedItem(response, action.item.path)
                            }
                        } else if (action.type === 'create') {
                            const response = await api.fileSystem.create(action.item)
                            actions.createSavedItem(response)
                        } else if (action.type === 'delete' && action.item.id) {
                            await api.fileSystem.delete(action.item.id)
                            actions.deleteSavedItem(action.item)
                        }
                        actions.removeQueuedAction(action)
                    }
                    return true
                },
                cancelPendingActions: async () => {
                    for (const action of values.pendingActions) {
                        actions.removeQueuedAction(action)
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
                    return {
                        ...state,
                        [folder]: state[folder].filter((item) => item.id !== savedItem.id),
                    }
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
        unfiledLoadingCount: [
            0,
            {
                loadUnfiledItems: (state) => state + 1,
                loadUnfiledItemsSuccess: (state) => state - 1,
                loadUnfiledItemsFailure: (state) => state - 1,
            },
        ],
        pendingActions: [
            [] as ProjectTreeAction[],
            {
                queueAction: (state, { action }) => [...state, action],
                removeQueuedAction: (state, { action }) => state.filter((a) => a !== action),
                cancelPendingActions: () => [],
            },
        ],
        expandedFolders: [
            [] as string[],
            { persist: true },
            {
                setExpandedFolders: (_, { folderIds }) => folderIds,
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
        unfiledLoading: [(s) => [s.unfiledLoadingCount], (unfiledLoadingCount) => unfiledLoadingCount > 0],
        unfiledItems: [
            // Remove from unfiledItems the ones that are in "savedItems"
            (s) => [s.savedItems, s.allUnfiledItems],
            (savedItems, allUnfiledItems): FileSystemEntry[] => {
                const urls = new Set<string>()
                for (const item of [...savedItems]) {
                    const key = `${item.type}/${item.ref}`
                    if (!urls.has(key)) {
                        urls.add(key)
                    }
                }
                return allUnfiledItems.filter((item) => !urls.has(`${item.type}/${item.ref}`))
            },
        ],
        viableItems: [
            // Combine unfiledItems with savedItems and apply pendingActions
            (s) => [s.unfiledItems, s.savedItems, s.pendingActions],
            (unfiledItems, savedItems, pendingActions): FileSystemEntry[] => {
                const items = [...unfiledItems, ...savedItems]
                const itemsByPath = Object.fromEntries(items.map((item) => [item.path, item]))
                for (const action of pendingActions) {
                    if (action.type === 'move' && action.newPath) {
                        const item = itemsByPath[action.path]
                        if (item) {
                            if (!itemsByPath[action.newPath]) {
                                itemsByPath[action.newPath] = { ...item, path: action.newPath }
                                delete itemsByPath[action.path]
                            } else {
                                console.error("Item already exists, can't move", action.newPath)
                            }
                        } else {
                            console.error("Item not found, can't move", action.path)
                        }
                    } else if (action.type === 'create' && action.newPath) {
                        if (!itemsByPath[action.newPath]) {
                            itemsByPath[action.newPath] = { ...action.item, path: action.newPath }
                        } else {
                            console.error("Item already exists, can't create", action.item)
                        }
                    } else if (action.type === 'delete' && action.path) {
                        delete itemsByPath[action.path]
                    }
                }
                return Object.values(itemsByPath)
            },
        ],
        unappliedPaths: [
            // Paths that are currently being loaded
            (s) => [s.pendingActions],
            (pendingActions) => {
                const unappliedPaths: Record<string, boolean> = {}
                for (const action of pendingActions) {
                    if (action.type === 'move-create' || action.type === 'move' || action.type === 'create') {
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
            (s) => [s.unfiledLoading, s.savedItemsLoading, s.pendingLoaderLoading, s.pendingActions],
            (unfiledLoading, savedItemsLoading, pendingLoaderLoading, pendingActions) => {
                const loadingPaths: Record<string, boolean> = {}
                if (unfiledLoading) {
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
            (s) => [s.viableItems, s.folderStates],
            (viableItems, folderStates): TreeDataItem[] =>
                convertFileSystemEntryToTreeDataItem(viableItems, folderStates, 'project'),
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
        defaultTreeNodes: [
            (s) => [s.featureFlags, s.groupNodes, s.folderStates],
            (_featureFlags, groupNodes: FileSystemImport[], folderStates) =>
                // .filter(f => !f.flag || featureFlags[f.flag])
                convertFileSystemEntryToTreeDataItem(getDefaultTree(groupNodes), folderStates, 'root'),
        ],
        searchedTreeItems: [
            (s) => [s.searchResults, s.searchResultsLoading],
            (searchResults, searchResultsLoading): TreeDataItem[] => {
                const results = convertFileSystemEntryToFlatTreeDataItem(
                    searchResults.results,
                    'search',
                    searchResults.searchTerm
                )
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
                            id: `project-loading/`,
                            name: 'Loading...',
                            icon: <Spinner />,
                        },
                    ]
                }
                return projectTree
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
                const response = await api.fileSystem.list({
                    parent: folder,
                    depth: splitPath(folder).length + 1,
                    limit: PAGINATION_LIMIT + 1,
                    offset: previousFiles.length,
                })

                let files = response.results
                let hasMore = false
                if (files.length > PAGINATION_LIMIT) {
                    files = files.slice(0, PAGINATION_LIMIT)
                    hasMore = true
                }
                actions.loadFolderSuccess(folder, [...previousFiles, ...files], hasMore)
            } catch (error) {
                actions.loadFolderFailure(folder, String(error))
            }
        },
        moveItem: async ({ oldPath, newPath }) => {
            for (const item of values.viableItems) {
                if (item.path === oldPath || item.path.startsWith(oldPath + '/')) {
                    actions.queueAction({
                        type: 'move',
                        item,
                        path: item.path,
                        newPath: newPath + item.path.slice(oldPath.length),
                    })
                }
            }
        },
        deleteItem: async ({ item }) => {
            actions.queueAction({ type: 'delete', item, path: item.path })
        },
        addFolder: ({ folder }) => {
            if (values.viableItems.find((item) => item.path === folder)) {
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
            if (values.expandedFolders.find((f) => f === folderId)) {
                actions.setExpandedFolders(values.expandedFolders.filter((f) => f !== folderId))
            } else {
                actions.setExpandedFolders([...values.expandedFolders, folderId])
                if (values.folderStates[folderId] !== 'loaded' && values.folderStates[folderId] !== 'loading') {
                    const folder = findInProjectTree(folderId, values.projectTree)
                    folder && actions.loadFolder(folder.record?.path)
                }
            }
        },
        cancelPendingActions: () => {
            // Clear all pending actions without applying them
            for (const action of values.pendingActions) {
                actions.removeQueuedAction(action)
            }
        },
        rename: ({ path }) => {
            const splits = splitPath(path)
            if (splits.length > 0) {
                const currentName = splits[splits.length - 1].replace(/\\/g, '')
                const folder = prompt('New name?', currentName)
                if (folder) {
                    actions.moveItem(path, joinPath([...splits.slice(0, -1), folder]))
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
    })),
    afterMount(({ actions }) => {
        actions.loadFolder('')
        actions.loadUnfiledItems()
    }),
])
