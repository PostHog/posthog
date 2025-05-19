import { IconPlus } from '@posthog/icons'
import { lemonToast, Link, ProfilePicture, Spinner } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { LemonTreeSelectMode, TreeDataItem, TreeTableViewKeys } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { groupsModel } from '~/models/groupsModel'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'
import { Breadcrumb, ProjectTreeBreadcrumb, ProjectTreeRef, UserBasicType } from '~/types'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { getDefaultTreeNew } from './defaultTree'
import type { projectTreeLogicType } from './projectTreeLogicType'
import { FolderState, ProjectTreeAction } from './types'
import {
    appendResultsToFolders,
    convertFileSystemEntryToTreeDataItem,
    findInProjectTree,
    joinPath,
    sortFilesAndFolders,
    splitPath,
    unescapePath,
} from './utils'

const PAGINATION_LIMIT = 100
const MOVE_ALERT_LIMIT = 50
const DELETE_ALERT_LIMIT = 0

export type ProjectTreeSortMethod = 'folder' | 'recent'

export interface RecentResults {
    results: FileSystemEntry[]
    startTime: string | null
    endTime: string | null
    hasMore: boolean
}

export interface SearchResults {
    searchTerm: string
    results: FileSystemEntry[]
    hasMore: boolean
    lastCount: number
}

export const projectTreeLogic = kea<projectTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'projectTreeLogic']),
    connect(() => ({
        values: [
            groupsModel,
            ['aggregationLabel', 'groupTypes', 'groupsAccessStatus'],
            featureFlagLogic,
            ['featureFlags'],
            panelLayoutLogic,
            ['searchTerm', 'projectTreeMode'],
            breadcrumbsLogic,
            ['projectTreeRef', 'appBreadcrumbs', 'sceneBreadcrumbs'],
        ],
        actions: [panelLayoutLogic, ['setSearchTerm', 'setProjectTreeMode']],
    })),
    actions({
        loadUnfiledItems: true,
        addFolder: (folder: string, editAfter = true, callback?: (folder: string) => void) => ({
            folder,
            editAfter,
            callback,
        }),
        deleteItem: (item: FileSystemEntry) => ({ item }),
        moveItem: (item: FileSystemEntry, newPath: string, force = false) => ({ item, newPath, force }),
        movedItem: (item: FileSystemEntry, oldPath: string, newPath: string) => ({ item, oldPath, newPath }),
        linkItem: (oldPath: string, newPath: string, force = false) => ({ oldPath, newPath, force }),
        queueAction: (action: ProjectTreeAction) => ({ action }),
        removeQueuedAction: (action: ProjectTreeAction) => ({ action }),
        createSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        deleteSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        setExpandedFolders: (folderIds: string[]) => ({ folderIds }),
        setExpandedSearchFolders: (folderIds: string[]) => ({ folderIds }),
        setLastViewedId: (id: string) => ({ id }),
        toggleFolderOpen: (folderId: string, isExpanded: boolean) => ({ folderId, isExpanded }),
        loadFolderIfNotLoaded: (folderId: string) => ({ folderId }),
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
        rename: (value: string, item: FileSystemEntry) => ({ value, item }),
        createFolder: (parentPath: string, editAfter = true, callback?: (folder: string) => void) => ({
            parentPath,
            editAfter,
            callback,
        }),
        loadSearchResults: (searchTerm: string, offset = 0) => ({ searchTerm, offset }),
        loadRecentResults: (type: 'start' | 'end') => ({ type }),
        assureVisibility: (projectTreeRef: ProjectTreeRef) => ({ projectTreeRef }),
        setLastNewFolder: (folder: string | null) => ({ folder }),
        onItemChecked: (id: string, checked: boolean, shift: boolean) => ({ id, checked, shift }),
        setLastCheckedItem: (id: string, checked: boolean, shift: boolean) => ({ id, checked, shift }),
        setCheckedItems: (checkedItems: Record<string, boolean>) => ({ checkedItems }),
        expandProjectFolder: (path: string) => ({ path }),
        moveCheckedItems: (path: string) => ({ path }),
        linkCheckedItems: (path: string) => ({ path }),
        deleteCheckedItems: true,
        checkSelectedFolders: true,
        syncTypeAndRef: (type: string, ref: string) => ({ type, ref }),
        deleteTypeAndRef: (type: string, ref: string) => ({ type, ref }),
        updateSyncedFiles: (files: FileSystemEntry[]) => ({ files }),
        scrollToView: (item: FileSystemEntry) => ({ item }),
        clearScrollTarget: true,
        setEditingItemId: (id: string) => ({ id }),
        setMovingItems: (items: FileSystemEntry[]) => ({ items }),
        setSortMethod: (sortMethod: ProjectTreeSortMethod) => ({ sortMethod }),
        setSelectMode: (selectMode: LemonTreeSelectMode) => ({ selectMode }),
        setTreeTableColumnSizes: (sizes: number[]) => ({ sizes }),
        addUsers: (users: UserBasicType[]) => ({ users }),
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
            { searchTerm: '', results: [], hasMore: false, lastCount: 0 } as SearchResults,
            {
                loadSearchResults: async ({ searchTerm, offset }, breakpoint) => {
                    await breakpoint(250)
                    const response = await api.fileSystem.list({
                        search: searchTerm,
                        offset,
                        limit: PAGINATION_LIMIT + 1,
                        orderBy: values.sortMethod === 'recent' ? '-created_at' : undefined,
                        notType: values.sortMethod === 'recent' ? 'folder' : undefined,
                    })
                    breakpoint()
                    const results = [
                        ...(offset > 0 && searchTerm === values.searchResults.searchTerm
                            ? values.searchResults.results
                            : []),
                        ...response.results.slice(0, PAGINATION_LIMIT),
                    ]
                    if (response.users?.length > 0) {
                        actions.addUsers(response.users)
                    }
                    return {
                        searchTerm,
                        results: values.sortMethod === 'recent' ? results : results.sort(sortFilesAndFolders),
                        hasMore: response.results.length > PAGINATION_LIMIT,
                        lastCount: Math.min(response.results.length, PAGINATION_LIMIT),
                    }
                },
            },
        ],
        recentResults: [
            { results: [], hasMore: false, startTime: null, endTime: null } as RecentResults,
            {
                loadRecentResults: async ({ type }, breakpoint) => {
                    await breakpoint(250)
                    const params = {
                        orderBy: '-created_at',
                        notType: 'folder',
                        limit: PAGINATION_LIMIT + 1,
                        createdAtGt:
                            type === 'start' && values.recentResults.startTime
                                ? values.recentResults.startTime
                                : undefined,
                        createdAtLt:
                            type === 'end' && values.recentResults.endTime ? values.recentResults.endTime : undefined,
                    }
                    const response = await api.fileSystem.list(params)
                    const returnedResults = response.results.slice(0, PAGINATION_LIMIT)
                    const hasMore = response.results.length > PAGINATION_LIMIT
                    breakpoint()
                    const seenIds = new Set()
                    const results = [...values.recentResults.results, ...returnedResults]
                        .filter((item) => {
                            if (seenIds.has(item.id)) {
                                return false
                            }
                            seenIds.add(item.id)
                            return true
                        })
                        .sort((a, b) => {
                            return new Date(b.created_at ?? '').getTime() - new Date(a.created_at ?? '').getTime()
                        })
                    if (response.users?.length > 0) {
                        actions.addUsers(response.users)
                    }
                    return {
                        results,
                        hasMore,
                        startTime: response.results[0]?.created_at ?? null,
                        endTime: response.results[response.results.length - 1]?.created_at ?? null,
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
                                const confirmMessage = `Delete the folder "${splitPath(
                                    action.item.path
                                ).pop()}" and move ${response.count} items back into "Unfiled"?`
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
                    return {
                        ...state,
                        [folder]: (state[folder] || []).find((f) => f.id === savedItem.id)
                            ? state[folder].map((item) => (item.id === savedItem.id ? savedItem : item))
                            : [...(state[folder] || []), savedItem],
                    }
                },
                loadSearchResultsSuccess: (state, { searchResults }) => {
                    return appendResultsToFolders(searchResults, state)
                },
                loadRecentResultsSuccess: (state, { recentResults }) => {
                    return appendResultsToFolders(recentResults, state)
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
                    const newState = { ...state }
                    for (const file of files) {
                        const folder = joinPath(splitPath(file.path).slice(0, -1))
                        if (newState[folder]) {
                            if (newState[folder].find((f) => f.id === file.id)) {
                                newState[folder] = newState[folder].map((f) =>
                                    f.id === file.id ? { ...f, ...file } : f
                                )
                            } else {
                                newState[folder] = [...newState[folder], file]
                            }
                        } else {
                            newState[folder] = [file]
                        }
                    }
                    return newState
                },
                deleteTypeAndRef: (state, { type, ref }) => {
                    const newState = { ...state }
                    for (const [folder, files] of Object.entries(newState)) {
                        if (
                            files.some(
                                (file) =>
                                    (type.endsWith('/') ? file.type?.startsWith(type) : file.type === type) &&
                                    file.ref === ref
                            )
                        ) {
                            newState[folder] = files.filter(
                                (file) =>
                                    (type.endsWith('/') ? !file.type?.startsWith(type) : file.type !== type) ||
                                    file.ref !== ref
                            )
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
        searchResults: [
            { searchTerm: '', results: [], hasMore: false, lastCount: 0 } as SearchResults,
            {
                movedItem: (state, { newPath, item }) => {
                    if (state.searchTerm && state.results.length > 0) {
                        const newResults = state.results.map((result) => {
                            if (result.id === item.id) {
                                return { ...item, path: newPath }
                            }
                            return result
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
                deleteSavedItem: (state, { savedItem }) => {
                    if (state.searchTerm && state.results.length > 0) {
                        const newResults = state.results.filter((result) => result.id !== savedItem.id)
                        return { ...state, results: newResults }
                    }
                    return state
                },
                deleteTypeAndRef: (state, { type, ref }) => {
                    return {
                        ...state,
                        results: state.results.filter(
                            (file) =>
                                (type.endsWith('/') ? !file.type?.startsWith(type) : file.type !== type) ||
                                file.ref !== ref
                        ),
                    }
                },
                updateSyncedFiles: (state, { files }) => {
                    const newIdsSet = new Set(files.map((file) => file.id))
                    const hasAnyNewIds = state.results.some((file) => newIdsSet.has(file.id))
                    if (hasAnyNewIds) {
                        const newResults = state.results.map((result) => {
                            if (newIdsSet.has(result.id)) {
                                const file = files.find((file) => file.id === result.id)
                                return { ...result, ...file }
                            }
                            return result
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
            },
        ],
        recentResults: [
            { results: [], hasMore: false, startTime: null, endTime: null } as RecentResults,
            {
                movedItem: (state, { newPath, item }) => {
                    if (state.results.length > 0) {
                        const newResults = state.results.map((result) => {
                            if (result.id === item.id) {
                                return { ...item, path: newPath }
                            }
                            return result
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
                deleteSavedItem: (state, { savedItem }) => {
                    if (state.results.length > 0) {
                        const newResults = state.results.filter((result) => result.id !== savedItem.id)
                        return { ...state, results: newResults }
                    }
                    return state
                },
                deleteTypeAndRef: (state, { type, ref }) => {
                    return {
                        ...state,
                        results: state.results.filter(
                            (file) =>
                                (type.endsWith('/') ? !file.type?.startsWith(type) : file.type !== type) ||
                                file.ref !== ref
                        ),
                    }
                },
                createSavedItem: (state, { savedItem }) => {
                    if (state.results.find((result) => result.id === savedItem.id)) {
                        return {
                            ...state,
                            results: state.results.map((result) => (result.id === savedItem.id ? savedItem : result)),
                        }
                    } else if (savedItem.created_at && savedItem.type !== 'folder') {
                        const newResults = [...state.results, savedItem].sort((a, b) => {
                            return new Date(b.created_at ?? '').getTime() - new Date(a.created_at ?? '').getTime()
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
                updateSyncedFiles: (state, { files }) => {
                    const newIdsSet = new Set(files.map((file) => file.id))
                    const hasAnyNewIds = state.results.some((file) => newIdsSet.has(file.id))
                    if (hasAnyNewIds) {
                        const newResults = state.results.map((result) => {
                            if (newIdsSet.has(result.id)) {
                                const file = files.find((file) => file.id === result.id)
                                return { ...result, ...file }
                            }
                            return result
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
            },
        ],
        users: [
            {} as Record<string, UserBasicType>,
            {
                addUsers: (state, { users }) => {
                    if (!users || users.length === 0) {
                        return state
                    }
                    const newState = { ...state }
                    for (const user of users) {
                        newState[user.id] = user
                    }
                    return newState
                },
            },
        ],
        lastNewFolder: [
            null as string | null,
            {
                setLastNewFolder: (_, { folder }) => {
                    return folder ?? null
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
        movingItems: [
            [] as FileSystemEntry[],
            {
                setMovingItems: (_, { items }) => items,
            },
        ],
        lastCheckedItem: [
            null as { id: string; checked: boolean; shift: boolean } | null,
            {
                setLastCheckedItem: (_, { id, checked, shift }) => ({ id, checked, shift }),
            },
        ],
        scrollTargetId: [
            '' as string,
            {
                scrollToView: (_, { item }) =>
                    item.type === 'folder' ? `project-folder/${item.path}` : `project/${item.id}`,
                clearScrollTarget: () => '',
            },
        ],
        editingItemId: [
            '',
            {
                setEditingItemId: (_, { id }) => id,
            },
        ],
        sortMethod: [
            'alphabetical' as ProjectTreeSortMethod,
            {
                setSortMethod: (_, { sortMethod }) => sortMethod,
            },
        ],
        selectMode: [
            'default' as LemonTreeSelectMode,
            {
                setSelectMode: (_, { selectMode }) => selectMode,
            },
        ],
        treeTableColumnSizes: [
            [350, 200, 200, 200] as number[],
            { persist: true },
            {
                setTreeTableColumnSizes: (_, { sizes }) => sizes,
            },
        ],
    }),
    selectors({
        treeTableColumnOffsets: [
            (s) => [s.treeTableColumnSizes],
            (sizes): number[] => sizes.map((_, index) => sizes.slice(0, index).reduce((acc, s) => acc + s, 0)),
        ],
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
            (viableItems): FileSystemEntry[] => [...viableItems].sort(sortFilesAndFolders),
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
            (s) => [s.viableItems, s.folderStates, s.checkedItems, s.users],
            (viableItems, folderStates, checkedItems, users): TreeDataItem[] =>
                convertFileSystemEntryToTreeDataItem({
                    imports: viableItems,
                    folderStates,
                    checkedItems,
                    root: 'project',
                    users,
                }),
        ],
        projectTreeOnlyFolders: [
            (s) => [s.viableItems, s.folderStates, s.checkedItems, s.users],
            (viableItems, folderStates, checkedItems, users): TreeDataItem[] => [
                {
                    id: '/',
                    name: '/',
                    displayName: <>Project root</>,
                    record: { type: 'folder', path: '' },
                    children: convertFileSystemEntryToTreeDataItem({
                        imports: viableItems,
                        folderStates,
                        checkedItems,
                        root: 'project',
                        disabledReason: (item) => (item.type !== 'folder' ? 'Only folders can be selected' : undefined),
                        users,
                    }),
                },
            ],
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
                                  href: urls.groups(0),
                              },
                          ]
                        : Array.from(groupTypes.values()).map((groupType) => ({
                              path: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                              href: urls.groups(groupType.group_type_index),
                          }))),
                ]

                return groupNodes
            },
        ],
        treeItemsNew: [
            (s) => [s.featureFlags, s.folderStates, s.users],
            (featureFlags, folderStates, users): TreeDataItem[] =>
                convertFileSystemEntryToTreeDataItem({
                    imports: getDefaultTreeNew().filter(
                        (f) => !f.flag || (featureFlags as Record<string, boolean>)[f.flag]
                    ),
                    checkedItems: {},
                    folderStates,
                    root: 'new',
                    users,
                    foldersFirst: false,
                }),
        ],
        recentTreeItems: [
            (s) => [s.recentResults, s.recentResultsLoading, s.folderStates, s.checkedItems, s.users],
            (recentResults, recentResultsLoading, folderStates, checkedItems, users): TreeDataItem[] => {
                const results = convertFileSystemEntryToTreeDataItem({
                    imports: recentResults.results,
                    folderStates,
                    checkedItems,
                    root: 'project',
                    disableFolderSelect: true,
                    recent: true,
                    users,
                })
                if (recentResultsLoading) {
                    results.push({
                        id: `recent-loading/`,
                        name: 'Loading...',
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })
                } else if (recentResults.hasMore) {
                    results.push({
                        id: `recent-load-more/`,
                        name: 'Load more...',
                        icon: <IconPlus />,
                        disableSelect: true,
                        onClick: () => projectTreeLogic.actions.loadRecentResults('end'),
                    })
                }
                return results
            },
        ],
        searchedTreeItems: [
            (s) => [s.searchResults, s.searchResultsLoading, s.folderStates, s.checkedItems, s.sortMethod, s.users],
            (searchResults, searchResultsLoading, folderStates, checkedItems, sortMethod, users): TreeDataItem[] => {
                const results = convertFileSystemEntryToTreeDataItem({
                    imports: searchResults.results,
                    folderStates,
                    checkedItems,
                    root: 'project',
                    searchTerm: searchResults.searchTerm,
                    disableFolderSelect: true,
                    recent: sortMethod === 'recent',
                    users,
                })
                if (searchResultsLoading) {
                    results.push({
                        id: `search-loading/`,
                        name: 'Loading...',
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })
                } else if (searchResults.hasMore) {
                    results.push({
                        id: `search-load-more/${searchResults.searchTerm}`,
                        name: 'Load more...',
                        icon: <IconPlus />,
                        disableSelect: true,
                        onClick: () =>
                            projectTreeLogic.actions.loadSearchResults(
                                searchResults.searchTerm,
                                searchResults.results.length
                            ),
                    })
                }
                return results
            },
        ],
        projectTreeItems: [
            (s) => [s.searchTerm, s.searchedTreeItems, s.projectTree, s.loadingPaths, s.recentTreeItems, s.sortMethod],
            (searchTerm, searchedTreeItems, projectTree, loadingPaths, recentTreeItems, sortMethod): TreeDataItem[] => {
                if (searchTerm) {
                    return searchedTreeItems
                }
                if (sortMethod === 'recent') {
                    return recentTreeItems
                }
                if (loadingPaths[''] && projectTree.length === 0) {
                    return [
                        {
                            id: `folder-loading/`,
                            name: 'Loading...',
                            icon: <Spinner />,
                            type: 'loading-indicator',
                        },
                    ]
                }
                return projectTree
            },
        ],
        // TODO: use treeData + some other logic to determine the keys
        treeTableKeys: [
            (s) => [s.treeTableColumnSizes, s.treeTableColumnOffsets, s.sortMethod, s.users, s.projectTreeMode],
            (sizes, offsets, sortMethod, users, projectTreeMode): TreeTableViewKeys => ({
                headers: [
                    {
                        key: 'name',
                        title: 'Name',
                        tooltip: (value: string) => value,
                        width: sizes[0],
                        offset: offsets[0],
                    },
                    {
                        key: 'record.meta.created_at',
                        title: 'Created at',
                        formatComponent: (created_at) =>
                            created_at ? (
                                <span className="text-muted text-xs">{dayjs(created_at).fromNow()}</span>
                            ) : (
                                '-'
                            ),
                        formatString: (created_at) => (created_at ? dayjs(created_at).fromNow() : '-'),
                        tooltip: (created_at) => (created_at ? dayjs(created_at).format('MMM D, YYYY HH:mm:ss') : ''),
                        width: sizes[1],
                        offset: offsets[1],
                    },
                    {
                        key: 'record.meta.created_by',
                        title: 'Created by',
                        formatComponent: (created_by) =>
                            created_by && users[created_by] ? (
                                <Link
                                    to={urls.personByDistinctId(users[created_by].distinct_id)}
                                    onClick={(e) => {
                                        e.preventDefault()
                                        e.stopPropagation()
                                        router.actions.push(urls.personByDistinctId(users[created_by].distinct_id))
                                        if (projectTreeMode === 'table') {
                                            projectTreeLogic.actions.setProjectTreeMode('tree')
                                        }
                                    }}
                                >
                                    <ProfilePicture user={users[created_by]} size="sm" className="mr-1" />
                                    <span>
                                        {users[created_by].first_name} {users[created_by].last_name}
                                    </span>
                                </Link>
                            ) : (
                                '-'
                            ),
                        formatString: (created_by) =>
                            created_by && users[created_by]
                                ? `${users[created_by].first_name} ${users[created_by].last_name}`
                                : '-',
                        width: sizes[2],
                        offset: offsets[2],
                    },
                    ...(sortMethod === 'recent'
                        ? [
                              {
                                  key: 'record.path',
                                  title: 'Folder',
                                  formatString: (value: string) =>
                                      value ? joinPath(splitPath(value).slice(0, -1)) : '',
                                  tooltip: (value: string) => (value ? joinPath(splitPath(value).slice(0, -1)) : ''),
                                  width: sizes[3] || 200,
                                  offset: offsets[3],
                              },
                          ]
                        : []),
                ],
            }),
        ],
        treeTableTotalWidth: [(s) => [s.treeTableColumnSizes], (sizes): number => sizes.reduce((acc, s) => acc + s, 0)],
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
        checkedItemsArray: [
            (s) => [s.checkedItems, s.viableItemsById],
            (checkedItems, viableItemsById): FileSystemEntry[] => {
                return Object.entries(checkedItems)
                    .filter(([_, checked]) => checked)
                    .map(([id]) => viableItemsById[id])
                    .filter(Boolean)
            },
        ],

        projectTreeRefEntry: [
            (s) => [s.projectTreeRef, s.sortedItems],
            (projectTreeRef, sortedItems): FileSystemEntry | null => {
                if (!projectTreeRef || !projectTreeRef.type || !projectTreeRef.ref) {
                    return null
                }
                const treeItem = projectTreeRef.type.endsWith('/')
                    ? sortedItems.find(
                          (item) => item.type?.startsWith(projectTreeRef.type) && item.ref === projectTreeRef.ref
                      )
                    : sortedItems.find((item) => item.type === projectTreeRef.type && item.ref === projectTreeRef.ref)
                return treeItem ?? null
            },
        ],
        projectTreeRefBreadcrumbs: [
            (s) => [s.projectTreeRef, s.projectTreeRefEntry, s.lastNewFolder, s.appBreadcrumbs, s.sceneBreadcrumbs],
            (
                projectTreeRef,
                projectTreeRefEntry,
                lastNewFolder,
                appBreadcrumbs,
                sceneBreadcrumbs
            ): Breadcrumb[] | null => {
                let folders: string[] = []

                // Take the last breadcrumb from the scene (may contain some edit state logic)
                let lastBreadcrumb: Breadcrumb | null =
                    sceneBreadcrumbs.length > 0 ? sceneBreadcrumbs.slice(-1)[0] : null

                // :HACK: Ignore last breadcrumb for the messaging scenes to avoid showing static titles
                if (
                    projectTreeRef?.type &&
                    projectTreeRef.ref !== null &&
                    ['hog_function/campaign', 'hog_function/broadcast'].includes(projectTreeRef.type)
                ) {
                    lastBreadcrumb = null
                }

                // If we're on a page that's in the project tree, take its path as our base
                if (projectTreeRefEntry?.path) {
                    folders = splitPath(projectTreeRefEntry.path)
                    const name = folders.pop() // remove last part
                    if (!lastBreadcrumb) {
                        // No scene breadcrumbs, so create a new one with the file name
                        lastBreadcrumb = {
                            key: `project-tree/${projectTreeRefEntry.path}`,
                            name: unescapePath(name ?? 'Unnamed'),
                            path: projectTreeRefEntry.href, // link to actual page
                        }
                    }
                }
                // If we're on a "new xyz" page opened from a folder, use that folder as the base
                if (!projectTreeRefEntry && projectTreeRef?.ref === null && lastNewFolder) {
                    folders = splitPath(lastNewFolder)
                    if (!lastBreadcrumb) {
                        lastBreadcrumb = {
                            key: `new/${lastNewFolder}`,
                            name: 'New',
                            path: joinPath([...folders, 'New']),
                        }
                    }
                }
                // Convert the folders into breadcrumbs
                const breadcrumbs: ProjectTreeBreadcrumb[] = folders.map((path, index) => ({
                    key: `project-tree/${path}`,
                    name: unescapePath(path),
                    path: joinPath(folders.slice(0, index + 1)),
                    type: 'folder',
                }))
                return [...appBreadcrumbs, ...breadcrumbs, ...(lastBreadcrumb ? [lastBreadcrumb] : [])]
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
                if (response.users?.length > 0) {
                    actions.addUsers(response.users)
                }
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
        deleteSavedItem: () => {
            actions.checkSelectedFolders()
        },
        movedItem: () => {
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
                        if (item.type === 'folder' && checkedItems[`project-folder/${item.path}`]) {
                            checkingFolder = item.path
                        }
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
        onItemChecked: ({ id, checked, shift }) => {
            const {
                sortedItems,
                searchResults,
                sortMethod,
                recentResults,
                viableItemsById,
                lastCheckedItem,
                checkedItems: prevChecked,
            } = values
            const clickedItem = viableItemsById[id]
            if (!clickedItem) {
                // should never happen
                return
            }
            const isSearching = !!values.searchTerm
            const shownItems = isSearching
                ? searchResults.results
                : sortMethod === 'recent'
                ? recentResults.results
                : sortedItems

            const checkedItems = { ...prevChecked }

            const itemKey = (item: FileSystemEntry): string =>
                item.type === 'folder' ? `project-folder/${item.path}` : `project/${item.id}`

            const markItem = (item: FileSystemEntry, value: boolean): void => {
                checkedItems[itemKey(item)] = value
            }

            const markFolderContents = (folder: FileSystemEntry, value: boolean): void => {
                if (isSearching) {
                    return
                }
                const startIdx = shownItems.findIndex((i) => i.id === folder.id)
                for (let i = startIdx + 1; i < shownItems.length; i++) {
                    const entry = shownItems[i]
                    if (!entry.path.startsWith(folder.path + '/')) {
                        // left the folder
                        break
                    }
                    markItem(entry, value)
                }
            }

            const applyToItem = (item: FileSystemEntry): void => {
                markItem(item, !!checked)
                if (item.type === 'folder') {
                    markFolderContents(item, !!checked)
                }
            }

            if (shift && lastCheckedItem) {
                const prevIdx = shownItems.findIndex((it) => itemKey(it) === lastCheckedItem.id)
                const currIdx = shownItems.findIndex((it) => it.id === clickedItem.id)
                if (prevIdx !== -1 && currIdx !== -1) {
                    const [start, end] = [Math.min(prevIdx, currIdx), Math.max(prevIdx, currIdx)]
                    for (let i = start; i <= end; i++) {
                        applyToItem(shownItems[i])
                    }
                } else if (currIdx !== -1) {
                    applyToItem(shownItems[currIdx])
                }
            } else {
                applyToItem(clickedItem)
            }

            actions.setLastCheckedItem(id, checked, shift)
            actions.setCheckedItems(checkedItems)

            // If any items are checked, set the select mode to multi
            // We don't do the inverse because we don't want to set the select mode to default when deselecting all
            if (Object.values(checkedItems).some((v) => !!v)) {
                actions.setSelectMode('multi')
            }
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
        addFolder: ({ folder, editAfter, callback }) => {
            // Like Mac, we don't allow duplicate folder names
            // So we need to increment the folder name until we find a unique one
            let folderName = folder
            let counter = 2
            while (values.viableItems.find((item) => item.path === folderName && item.type === 'folder')) {
                folderName = `${folder} ${counter}`
                counter++
            }

            actions.queueAction({
                type: 'create',
                item: { id: `project/${folderName}`, path: folderName, type: 'folder' },
                path: folderName,
                newPath: folderName,
            })

            // Always set the editing item ID after a short delay to ensure the folder is in the DOM
            if (editAfter) {
                setTimeout(() => {
                    actions.setEditingItemId(`project-folder/${folderName}`)
                }, 50)
            }
            callback?.(folderName)
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
                    actions.loadFolderIfNotLoaded(folderId)
                }
            }
        },
        loadFolderIfNotLoaded: ({ folderId }) => {
            if (values.folderStates[folderId] !== 'loaded' && values.folderStates[folderId] !== 'loading') {
                const folder = findInProjectTree(folderId, values.projectTree)
                if (folder) {
                    actions.loadFolder(folder.record?.path)
                } else if (folderId.startsWith('project-folder/')) {
                    actions.loadFolder(folderId.slice('project-folder/'.length))
                }
            }
        },
        rename: ({ value, item }) => {
            const splits = splitPath(item.path)
            if (splits.length > 0) {
                if (value) {
                    actions.moveItem(item, joinPath([...splits.slice(0, -1), value]))
                    actions.setEditingItemId('')
                }
            }
        },
        createFolder: ({ parentPath, editAfter, callback }) => {
            const parentSplits = parentPath ? splitPath(parentPath) : []
            const newPath = joinPath([...parentSplits, 'Untitled folder'])
            actions.addFolder(newPath, editAfter, callback)
        },
        setSearchTerm: ({ searchTerm }) => {
            actions.loadSearchResults(searchTerm)
        },
        setSortMethod: ({ sortMethod }) => {
            if (values.searchTerm) {
                actions.loadSearchResults(values.searchTerm, 0)
            }
            if (sortMethod === 'recent' && !values.recentResultsLoading) {
                actions.loadRecentResults('start')
            }
        },
        assureVisibility: async ({ projectTreeRef }, breakpoint) => {
            if (projectTreeRef) {
                if (projectTreeRef.type === 'folder' && projectTreeRef.ref) {
                    actions.expandProjectFolder(projectTreeRef.ref)
                    const item = values.viableItems.find(
                        (item) => item.type === 'folder' && item.path === projectTreeRef.ref
                    )
                    if (item) {
                        actions.scrollToView(item)
                    }
                    return
                }

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
                } else if (projectTreeRef.ref !== null) {
                    const resp = await api.fileSystem.list(
                        projectTreeRef.type.endsWith('/')
                            ? { ref: projectTreeRef.ref, type__startswith: projectTreeRef.type }
                            : { ref: projectTreeRef.ref, type: projectTreeRef.type }
                    )
                    breakpoint() // bail if we opened some other item in the meanwhile
                    if (resp.users?.length > 0) {
                        actions.addUsers(resp.users)
                    }
                    if (resp.results && resp.results.length > 0) {
                        const result = resp.results[0]
                        path = result.path
                        actions.createSavedItem(result)
                    }
                }

                if (path) {
                    actions.expandProjectFolder(path)
                    if (treeItem) {
                        actions.scrollToView(treeItem)
                    }
                }
            }
        },
        syncTypeAndRef: async ({ type, ref }) => {
            const items = await (type.endsWith('/')
                ? api.fileSystem.list({ type__startswith: type, ref })
                : api.fileSystem.list({ type, ref }))
            if (items.users?.length > 0) {
                actions.addUsers(items.users)
            }
            actions.updateSyncedFiles(items.results)
        },
        setLastNewFolder: ({ folder }) => {
            if (folder) {
                actions.assureVisibility({ type: 'folder', ref: folder })
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        projectTreeRef: (newRef: ProjectTreeRef | null) => {
            if (newRef) {
                if (newRef.ref === null) {
                    if (typeof values.lastNewFolder === 'string') {
                        actions.assureVisibility({ type: 'folder', ref: values.lastNewFolder })
                    }
                } else {
                    actions.assureVisibility(newRef)
                }
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

export function deleteFromTree(type: string, ref: string): void {
    projectTreeLogic.findMounted()?.actions.deleteTypeAndRef(type, ref)
}

export function getLastNewFolder(): string | undefined {
    return projectTreeLogic.findMounted()?.values.lastNewFolder ?? undefined
}
