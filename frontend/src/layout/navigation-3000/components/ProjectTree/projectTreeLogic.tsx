import { IconBook, IconUpload } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { FileSystemEntry, FileSystemType } from '~/queries/schema/schema-general'

import { getDefaultTree } from './defaultTree'
import type { projectTreeLogicType } from './projectTreeLogicType'
import { FileSystemImport, ProjectTreeAction } from './types'
import { convertFileSystemEntryToTreeDataItem, joinPath, splitPath } from './utils'

export const projectTreeLogic = kea<projectTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'projectTreeLogic']),
    connect({
        values: [
            groupsModel,
            ['aggregationLabel', 'groupTypes', 'groupsAccessStatus'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    }),
    actions({
        loadSavedItems: true,
        loadUnfiledItems: (type?: FileSystemType) => ({ type }),
        addFolder: (folder: string) => ({ folder }),
        deleteItem: (item: FileSystemEntry) => ({ item }),
        moveItem: (oldPath: string, newPath: string) => ({ oldPath, newPath }),
        queueAction: (action: ProjectTreeAction) => ({ action }),
        removeQueuedAction: (action: ProjectTreeAction) => ({ action }),
        applyPendingActions: true,
        createSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        updateSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        deleteSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        updateExpandedFolders: (folders: string[]) => ({ folders }),
        updateActiveFolder: (folder: string | null) => ({ folder }),
        updateLastViewedPath: (path: string) => ({ path }),
        toggleFolder: (folder: string, isExpanded: boolean) => ({ folder, isExpanded }),
        updateSelectedFolder: (folder: string) => ({ folder }),
        updateHelpNoticeVisibility: (visible: boolean) => ({ visible }),
    }),
    loaders(({ actions, values }) => ({
        savedItems: [
            [] as FileSystemEntry[],
            {
                loadSavedItems: async () => {
                    const response = await api.fileSystem.list()
                    return [...values.savedItems, ...response.results]
                },
            },
        ],
        allUnfiledItems: [
            [] as FileSystemEntry[],
            {
                loadUnfiledItems: async ({ type }) => {
                    const response = await api.fileSystem.unfiled(type)
                    return [...values.allUnfiledItems, ...response.results]
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
                                actions.updateSavedItem(response)
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
            },
        ],
    })),
    reducers({
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
            },
        ],
        savedItems: [
            [] as FileSystemEntry[],
            {
                createSavedItem: (state, { savedItem }) => [...state, savedItem],
                updateSavedItem: (state, { savedItem }) =>
                    state.map((item) => (item.id === savedItem.id ? savedItem : item)),
                deleteSavedItem: (state, { savedItem }) => state.filter((item) => item.id !== savedItem.id),
            },
        ],
        expandedFolders: [
            [] as string[],
            { persist: true },
            {
                updateExpandedFolders: (_, { folders }) => folders,
            },
        ],
        activeFolder: [
            null as string | null,
            { persist: true },
            {
                updateActiveFolder: (_, { folder }) => folder,
            },
        ],
        lastViewedPath: [
            '',
            { persist: true },
            {
                updateLastViewedPath: (_, { path }) => path,
            },
        ],
        helpNoticeVisible: [
            true,
            { persist: true },
            {
                updateHelpNoticeVisibility: (_, { visible }) => visible,
            },
        ],
    }),
    selectors({
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
            (s) => [s.viableItems],
            (viableItems): TreeDataItem[] => convertFileSystemEntryToTreeDataItem(viableItems),
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
        defaultTreeNodes: [
            (s) => [s.featureFlags, s.groupNodes],
            (_featureFlags, groupNodes: FileSystemImport[]) =>
                // .filter(f => !f.flag || featureFlags[f.flag])
                convertFileSystemEntryToTreeDataItem(getDefaultTree(groupNodes)),
        ],
        projectRow: [
            (s) => [s.pendingActionsCount, s.pendingLoaderLoading],
            (pendingActionsCount, pendingLoaderLoading): TreeDataItem[] => [
                ...(pendingActionsCount > 0
                    ? [
                          {
                              id: '__apply_pending_actions__',
                              name: `--- Apply${
                                  pendingLoaderLoading ? 'ing' : ''
                              } ${pendingActionsCount} unsaved change${pendingActionsCount > 1 ? 's' : ''} ---`,
                              icon: pendingLoaderLoading ? <Spinner /> : <IconUpload className="text-warning" />,
                              onClick: !pendingLoaderLoading
                                  ? () => projectTreeLogic.actions.applyPendingActions()
                                  : undefined,
                          },
                      ]
                    : [
                          {
                              id: '__separator__',
                              name: '',
                          },
                      ]),
                {
                    id: 'project',
                    name: 'Default Project',
                    icon: <IconBook />,
                    record: { type: 'project', id: 'project' },
                    onClick: () => router.actions.push(urls.projectHomepage()),
                },
            ],
        ],
        treeData: [
            (s) => [s.defaultTreeNodes, s.projectTree, s.projectRow],
            (defaultTreeNodes, projectTree, projectRow): TreeDataItem[] => {
                return [...defaultTreeNodes, ...projectRow, ...projectTree]
            },
        ],
    }),
    listeners(({ actions, values }) => ({
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
        toggleFolder: ({ folder, isExpanded }) => {
            if (isExpanded) {
                actions.updateExpandedFolders(values.expandedFolders.filter((f) => f !== folder))
            } else {
                actions.updateExpandedFolders([...values.expandedFolders, folder])
            }
        },
        updateSelectedFolder: ({ folder }) => {
            actions.updateActiveFolder(folder)
            actions.updateLastViewedPath(folder)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSavedItems()
        actions.loadUnfiledItems('feature_flag')
        actions.loadUnfiledItems('experiment')
        actions.loadUnfiledItems('insight')
        actions.loadUnfiledItems('dashboard')
        actions.loadUnfiledItems('notebook')
    }),
])
