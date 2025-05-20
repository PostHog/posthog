import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { RecentResults, SearchResults } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { FolderState } from '~/layout/panel-layout/ProjectTree/types'
import { appendResultsToFolders, joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { UserBasicType } from '~/types'

import type { projectTreeDataLogicType } from './projectTreeDataLogicType'

export const PAGINATION_LIMIT = 100

export const projectTreeDataLogic = kea<projectTreeDataLogicType>([
    path(['layout', 'panel-layout', 'ProjectTree', 'projectTreeDataLogic']),
    actions({
        loadUnfiledItems: true,

        loadFolder: (folder: string) => ({ folder }),
        loadFolderIfNotLoaded: (folderId: string) => ({ folderId }),
        loadFolderStart: (folder: string) => ({ folder }),
        loadFolderSuccess: (folder: string, entries: FileSystemEntry[], hasMore: boolean, offsetIncrease: number) => ({
            folder,
            entries,
            hasMore,
            offsetIncrease,
        }),
        loadFolderFailure: (folder: string, error: string) => ({ folder, error }),

        addUsers: (users: UserBasicType[]) => ({ users }),
        addResults: (results: RecentResults | SearchResults) => ({ results }),

        createSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        deleteSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        movedItem: (item: FileSystemEntry, oldPath: string, newPath: string) => ({ item, oldPath, newPath }),

        syncTypeAndRef: (type: string, ref: string) => ({ type, ref }),
        deleteTypeAndRef: (type: string, ref: string) => ({ type, ref }),
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
    })),
    reducers({
        folders: [
            {} as Record<string, FileSystemEntry[]>,
            {
                loadFolderSuccess: (state, { folder, entries }) => ({ ...state, [folder]: entries }),
                addResults: (state, { results }) => appendResultsToFolders(results, state),
                createSavedItem: (state, { savedItem }) => {
                    const folder = joinPath(splitPath(savedItem.path).slice(0, -1))
                    return {
                        ...state,
                        [folder]: (state[folder] || []).find((f) => f.id === savedItem.id)
                            ? state[folder].map((item) => (item.id === savedItem.id ? savedItem : item))
                            : [...(state[folder] || []), savedItem],
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
        syncTypeAndRef: async ({ type, ref }) => {
            const items = await (type.endsWith('/')
                ? api.fileSystem.list({ type__startswith: type, ref })
                : api.fileSystem.list({ type, ref }))
            if (items.users?.length > 0) {
                actions.addUsers(items.users)
            }
            actions.addResults(items as SearchResults)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadFolder('')
        actions.loadUnfiledItems()
    }),
])
