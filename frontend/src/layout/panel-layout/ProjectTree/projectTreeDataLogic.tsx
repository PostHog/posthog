import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { IconPlus } from '@posthog/icons'

import api from 'lib/api'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'
import { urls } from 'scenes/urls'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import {
    getDefaultTreeData,
    getDefaultTreeNew,
    getDefaultTreePersons,
    getDefaultTreeProducts,
} from '~/layout/panel-layout/ProjectTree/defaultTree'
import { RecentResults, SearchResults, projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { FolderState, ProjectTreeAction } from '~/layout/panel-layout/ProjectTree/types'
import {
    appendResultsToFolders,
    convertFileSystemEntryToTreeDataItem,
    escapePath,
    formatUrlAsName,
    isGroupViewShortcut,
    joinPath,
    sortFilesAndFolders,
    splitPath,
} from '~/layout/panel-layout/ProjectTree/utils'
import { FEATURE_FLAGS } from '~/lib/constants'
import { groupsModel } from '~/models/groupsModel'
import { FileSystemEntry, FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'
import { UserBasicType } from '~/types'

import { panelLayoutLogic } from '../panelLayoutLogic'
import type { projectTreeDataLogicType } from './projectTreeDataLogicType'
import { getExperimentalProductsTree } from './projectTreeWebAnalyticsExperiment'

const MOVE_ALERT_LIMIT = 50
const DELETE_ALERT_LIMIT = 0
export const PAGINATION_LIMIT = 100

export const projectTreeDataLogic = kea<projectTreeDataLogicType>([
    path(['layout', 'panel-layout', 'ProjectTree', 'projectTreeDataLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            breadcrumbsLogic,
            ['projectTreeRef'],
            groupsModel,
            ['aggregationLabel', 'groupTypes', 'groupTypesLoading', 'groupsAccessStatus'],
        ],
        actions: [panelLayoutLogic, ['setActivePanelIdentifier']],
    })),
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

        addLoadedUsers: (users: UserBasicType[]) => ({ users }),
        addLoadedResults: (results: RecentResults | SearchResults) => ({ results }),

        createSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        deleteSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        deleteItem: (item: FileSystemEntry, projectTreeLogicKey: string) => ({ item, projectTreeLogicKey }),
        linkItem: (oldPath: string, newPath: string, force: boolean, projectTreeLogicKey: string) => ({
            oldPath,
            newPath,
            force,
            projectTreeLogicKey,
        }),
        moveItem: (item: FileSystemEntry, newPath: string, force: boolean, projectTreeLogicKey: string) => ({
            item,
            newPath,
            force,
            projectTreeLogicKey,
        }),
        movedItem: (item: FileSystemEntry, oldPath: string, newPath: string) => ({ item, oldPath, newPath }),
        queueAction: (action: ProjectTreeAction, projectTreeLogicKey: string) => ({ action, projectTreeLogicKey }),
        removeQueuedAction: (action: ProjectTreeAction) => ({ action }),

        syncTypeAndRef: (type: string, ref: string) => ({ type, ref }),
        deleteTypeAndRef: (type: string, ref: string) => ({ type, ref }),

        setLastNewFolder: (folder: string | null) => ({ folder }),

        addShortcutItem: (item: FileSystemEntry) => ({ item }),
        deleteShortcut: (id: FileSystemEntry['id']) => ({ id }),
        loadShortcuts: true,
    }),
    loaders(({ actions, values }) => ({
        unfiledItems: [
            false as boolean,
            {
                loadUnfiledItems: async () => {
                    if (!getCurrentTeamIdOrNone()) {
                        return false
                    }
                    const response = await api.fileSystem.unfiled()
                    if (response.results?.length > 0) {
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
        pendingLoader: [
            false,
            {
                queueAction: async ({ action, projectTreeLogicKey }) => {
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
                            actions.queueAction({ ...action, type: verb }, projectTreeLogicKey)
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
                                        actions.moveItem(
                                            { ...action.item, path: newPath },
                                            oldPath,
                                            false,
                                            projectTreeLogicKey
                                        )
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
                                        actions.deleteItem(response, projectTreeLogicKey)
                                    },
                                },
                            })

                            // Expand in the logic that called this data flow
                            projectTreeLogic
                                .findMounted({ key: projectTreeLogicKey })
                                ?.actions.expandProjectFolder(action.item.path)
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
                            actions.queueAction({ ...action, type: 'delete' }, projectTreeLogicKey)
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
        shortcutData: [
            [] as FileSystemEntry[],
            {
                loadShortcuts: async () => {
                    if (!getCurrentTeamIdOrNone()) {
                        return []
                    }

                    const response = await api.fileSystemShortcuts.list()
                    return response.results
                },
                addShortcutItem: async ({ item }) => {
                    const shortcutPath = joinPath([splitPath(item.path).pop() ?? 'Unnamed'])

                    const shortcutItem =
                        item.type === 'folder'
                            ? {
                                  path: shortcutPath,
                                  type: 'folder',
                                  ref: item.path,
                              }
                            : {
                                  path: shortcutPath,
                                  type: item.type,
                                  ref: item.ref,
                                  href: item.href,
                              }
                    const response = await api.fileSystemShortcuts.create(shortcutItem)
                    lemonToast.success('Shortcut created successfully', {
                        button: {
                            label: 'View',
                            dataAttr: 'project-tree-view-shortcuts',
                            action: () => {
                                actions.setActivePanelIdentifier('Shortcuts')
                            },
                        },
                    })
                    return [...values.shortcutData, response].sort((a, b) =>
                        a.path.toLowerCase().localeCompare(b.path.toLowerCase())
                    )
                },
                deleteShortcut: async ({ id }) => {
                    await api.fileSystemShortcuts.delete(id)
                    return values.shortcutData.filter((s) => s.id !== id)
                },
            },
        ],
    })),
    reducers({
        folders: [
            {} as Record<string, FileSystemEntry[]>,
            {
                loadFolderSuccess: (state, { folder, entries }) => ({ ...state, [folder]: entries }),
                addLoadedResults: (state, { results }) => appendResultsToFolders(results, state),
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
                addLoadedUsers: (state, { users }) => {
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
        pendingActions: [
            [] as ProjectTreeAction[],
            {
                queueAction: (state, { action }) => [...state, action],
                removeQueuedAction: (state, { action }) => state.filter((a) => a !== action),
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
        shortcutData: [
            [] as FileSystemEntry[],
            {
                deleteTypeAndRef: (state, { type, ref }) => state.filter((s) => s.type !== type || s.ref !== ref),
                addLoadedResults: (state, { results }) => {
                    const filesByTypeAndRef = Object.fromEntries(
                        results.results.map((file) => [`${file.type}//${file.ref}`, file])
                    )
                    return state.map((item) => {
                        const file = filesByTypeAndRef[`${item.type}//${item.ref}`]
                        if (file) {
                            return { ...item, path: escapePath(splitPath(file.path).pop() ?? 'Unnamed') }
                        }
                        return item
                    })
                },
            },
        ],
    }),
    selectors({
        savedItems: [
            (s) => [s.folders],
            (folders): FileSystemEntry[] =>
                Object.entries(folders).reduce((acc, [_, items]) => acc.concat(items), [] as FileSystemEntry[]),
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
                const itemsByPath = initialItems.reduce(
                    (acc, item) => {
                        acc[item.path] = acc[item.path] ? [...acc[item.path], item] : [item]
                        return acc
                    },
                    {} as Record<string, FileSystemEntry[]>
                )

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
                    (acc, item) =>
                        Object.assign(acc, {
                            [item.type === 'folder' ? 'project://' + item.path : 'project/' + item.id]: item,
                        }),
                    {} as Record<string, FileSystemEntry>
                ),
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
        groupItems: [
            (s) => [s.groupTypes, s.groupsAccessStatus, s.aggregationLabel, s.shortcutData, s.featureFlags],
            (groupTypes, groupsAccessStatus, aggregationLabel, shortcutData, featureFlags): FileSystemImport[] => {
                const showGroupsIntroductionPage = [
                    GroupsAccessStatus.HasAccess,
                    GroupsAccessStatus.HasGroupTypes,
                    GroupsAccessStatus.NoAccess,
                ].includes(groupsAccessStatus)

                const groupItems: FileSystemImport[] = showGroupsIntroductionPage
                    ? [
                          {
                              path: 'Groups',
                              category: 'Groups',
                              iconType: 'group',
                              href: urls.groups(0),
                              visualOrder: 30,
                          },
                      ]
                    : Array.from(groupTypes.values()).map((groupType) => ({
                          path: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                          category: 'Groups',
                          iconType: 'group',
                          href: urls.groups(groupType.group_type_index),
                          visualOrder: 30 + groupType.group_type_index,
                      }))

                // these are created when users save filtered views
                // from the groups page and should appear in the persons:// tree under "Saved Views"
                const groupFilterShortcuts = featureFlags[FEATURE_FLAGS.CRM_ITERATION_ONE]
                    ? shortcutData
                          .filter((shortcut) => isGroupViewShortcut(shortcut))
                          .map((shortcut) => ({
                              id: shortcut.id,
                              path: shortcut.path,
                              type: shortcut.type,
                              category: 'Saved Views',
                              iconType: 'group' as FileSystemIconType,
                              href: shortcut.href || '',
                              visualOrder: 100,
                              shortcut: true,
                              tags: shortcut.tags || [],
                          }))
                    : []

                return [...groupItems, ...groupFilterShortcuts]
            },
        ],
        getShortcutTreeItems: [
            (s) => [s.shortcutData, s.viableItems, s.folderStates, s.users, s.featureFlags],
            (
                shortcutData,
                viableItems,
                folderStates,
                users,
                featureFlags
            ): ((searchTerm: string, onlyFolders: boolean) => TreeDataItem[]) => {
                return function getStaticItems(searchTerm: string, onlyFolders: boolean): TreeDataItem[] {
                    const newShortcutData = []
                    for (const shortcut of shortcutData.filter(
                        // only remove shortcuts that are group view shortcuts when CRM iteration one is enabled
                        (shortcut) => !(featureFlags[FEATURE_FLAGS.CRM_ITERATION_ONE] && isGroupViewShortcut(shortcut))
                    )) {
                        const shortcutTreeItem = convertFileSystemEntryToTreeDataItem({
                            root: 'shortcuts://',
                            imports: [shortcut],
                            checkedItems: {},
                            folderStates,
                            users,
                            foldersFirst: true,
                            disabledReason: onlyFolders
                                ? (item) => (item.type !== 'folder' ? 'Only folders can be selected' : undefined)
                                : undefined,
                        })[0]

                        if (shortcut.type === 'folder' && shortcut.ref) {
                            const allImports = viableItems.filter((item) => item.path.startsWith(shortcut.ref + '/'))
                            let converted: TreeDataItem[] = convertFileSystemEntryToTreeDataItem({
                                root: 'project://',
                                imports: allImports.map((item) => ({ ...item, protocol: 'project://' })),
                                checkedItems: {},
                                folderStates,
                                users,
                                foldersFirst: true,
                                searchTerm,
                                disabledReason: onlyFolders
                                    ? (item) => (item.type !== 'folder' ? 'Only folders can be selected' : undefined)
                                    : undefined,
                            })
                            for (let i = 0; i < splitPath(shortcut.ref).length; i++) {
                                converted = converted[0]?.children || []
                            }
                            if (folderStates[shortcut.ref] === 'has-more') {
                                converted.push({
                                    id: `project://-load-more/${shortcut.ref}`,
                                    name: 'Load more...',
                                    displayName: <>Load more...</>,
                                    icon: <IconPlus />,
                                    disableSelect: true,
                                })
                            } else if (folderStates[shortcut.ref] === 'loading') {
                                converted.push({
                                    id: `project://-loading/${shortcut.ref}`,
                                    name: 'Loading...',
                                    displayName: <>Loading...</>,
                                    icon: <Spinner />,
                                    disableSelect: true,
                                    type: 'loading-indicator',
                                })
                            }

                            newShortcutData.push({ ...shortcutTreeItem, children: converted })
                        } else {
                            newShortcutData.push(shortcutTreeItem)
                        }
                    }
                    return newShortcutData
                }
            },
        ],
        getStaticTreeItems: [
            (s) => [s.featureFlags, s.getShortcutTreeItems, s.groupItems],
            (
                featureFlags,
                getShortcutTreeItems,
                groupItems
            ): ((searchTerm: string, onlyFolders: boolean) => TreeDataItem[]) => {
                const convert = (
                    imports: FileSystemImport[],
                    protocol: string,
                    searchTerm: string | undefined,
                    onlyFolders: boolean
                ): TreeDataItem[] =>
                    convertFileSystemEntryToTreeDataItem({
                        root: protocol,
                        imports: imports
                            .filter((f) => !f.flag || (featureFlags as Record<string, boolean>)[f.flag])
                            .map((i) => ({
                                ...i,
                                protocol,
                            })),
                        checkedItems: {},
                        folderStates: {},
                        users: {},
                        foldersFirst: false,
                        searchTerm,
                        disabledReason: onlyFolders
                            ? (item) => (item.type !== 'folder' ? 'Only folders can be selected' : undefined)
                            : undefined,
                    })
                return function getStaticItems(searchTerm: string, onlyFolders: boolean): TreeDataItem[] {
                    const data: [string, FileSystemImport[]][] = [
                        ['products://', getExperimentalProductsTree(featureFlags) || getDefaultTreeProducts()],
                        ['data://', getDefaultTreeData()],
                        ['persons://', [...getDefaultTreePersons(), ...groupItems]],
                        ['new://', getDefaultTreeNew()],
                    ]
                    const staticItems = data.map(([protocol, files]) => ({
                        id: protocol,
                        name: protocol,
                        displayName: <>{formatUrlAsName(protocol)}</>,
                        record: { type: 'folder', protocol, path: '' },
                        children: convert(files, protocol, searchTerm, onlyFolders),
                    }))
                    staticItems.push({
                        id: 'shortcuts://',
                        name: 'Shortcuts',
                        displayName: <>Shortcuts</>,
                        record: { type: 'folder', protocol: 'shortcuts://', path: '' },
                        children: getShortcutTreeItems(searchTerm, onlyFolders),
                    })
                    return staticItems
                }
            },
        ],
        treeItemsNew: [
            (s) => [s.getStaticTreeItems],
            (getStaticTreeItems) => getStaticTreeItems('', false).find((item) => item.id === 'new://')?.children ?? [],
        ],
        shortcutNonFolderPaths: [
            (s) => [s.shortcutData],
            (shortcutData) =>
                new Set(shortcutData.filter((shortcut) => shortcut.type !== 'folder').map((shortcut) => shortcut.path)),
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
                    actions.addLoadedUsers(response.users)
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
                actions.addLoadedUsers(items.users)
            }
            actions.addLoadedResults(items as any as SearchResults)
        },
        deleteItem: async ({ item, projectTreeLogicKey }) => {
            if (isGroupViewShortcut(item) && values.featureFlags[FEATURE_FLAGS.CRM_ITERATION_ONE]) {
                actions.deleteShortcut(item?.id)
                return
            }

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
            actions.queueAction(
                { type: item.type === 'folder' ? 'prepare-delete' : 'delete', item, path: item.path },
                projectTreeLogicKey
            )
        },
        moveItem: async ({ item, newPath, force, projectTreeLogicKey }) => {
            if (newPath === item.path) {
                return
            }
            if (!item.id) {
                lemonToast.error("Sorry, can't move an unsaved item (no id)")
                return
            }
            actions.queueAction(
                {
                    type: !force && item.type === 'folder' ? 'prepare-move' : 'move',
                    item,
                    path: item.path,
                    newPath: newPath,
                },
                projectTreeLogicKey
            )
        },
        linkItem: async ({ oldPath, newPath, force, projectTreeLogicKey }) => {
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
                actions.queueAction(
                    {
                        type: !force && item.type === 'folder' ? 'prepare-link' : 'link',
                        item,
                        path: item.path,
                        newPath: newPath + item.path.slice(oldPath.length),
                    },
                    projectTreeLogicKey
                )
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadFolder('')
        actions.loadUnfiledItems()
        actions.loadShortcuts()
    }),
])
