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
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { FileSystemEntry, FileSystemType } from '~/queries/schema/schema-general'

import { getDefaultTree } from './defaultTree'
import type { projectTreeLogicType } from './projectTreeLogicType'
import { FileSystemImport, ProjectTreeAction } from './types'
import { convertFileSystemEntryToTreeDataItem } from './utils'

export const projectTreeLogic = kea<projectTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'projectTreeLogic']),
    connect({
        values: [
            groupsModel,
            ['aggregationLabel', 'groupTypes', 'groupsAccessStatus'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeamName'],
        ],
    }),
    actions({
        loadSavedItems: true,
        loadUnfiledItems: (type?: FileSystemType) => ({ type }),
        addFolder: (folder: string) => ({ folder }),
        deleteItem: (item: FileSystemEntry) => ({ item }),
        moveItem: (oldFilePath: string, newFilePath: string) => ({ oldFilePath, newFilePath }),
        queueAction: (action: ProjectTreeAction) => ({ action }),
        removeQueuedAction: (action: ProjectTreeAction) => ({ action }),
        applyPendingActions: true,
        createSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        updateSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        deleteSavedItem: (savedItem: FileSystemEntry) => ({ savedItem }),
        setExpandedFolders: (folders: string[]) => ({ folders }),
        setActiveFolder: (folder: string | null) => ({ folder }),
        setLastViewedPath: (path: string) => ({ path }),
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
                        if (action.type === 'move' && action.newFilePath) {
                            if (!action.item.id) {
                                const response = await api.fileSystem.create({
                                    ...action.item,
                                    path: action.newFilePath,
                                })
                                actions.createSavedItem(response)
                            } else {
                                const response = await api.fileSystem.update(action.item.id, {
                                    path: action.newFilePath,
                                })
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
        loadingTree: [
            true, // Start as true since we load items on mount
            {
                loadSavedItems: () => true,
                loadSavedItemsSuccess: () => false,
                loadSavedItemsFailure: () => false,
                loadUnfiledItems: () => true,
                loadUnfiledItemsSuccess: () => false,
                loadUnfiledItemsFailure: () => false,
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
                setExpandedFolders: (_, { folders }) => folders,
            },
        ],
        activeFolder: [
            null as string | null,
            { persist: true },
            {
                setActiveFolder: (_, { folder }) => folder,
            },
        ],
        lastViewedPath: [
            '',
            { persist: true },
            {
                setLastViewedPath: (_, { path }) => path,
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
                    if (action.type === 'move' && action.newFilePath) {
                        const item = itemsByPath[action.filePath]
                        if (item) {
                            if (!itemsByPath[action.newFilePath]) {
                                itemsByPath[action.newFilePath] = { ...item, path: action.newFilePath }
                                delete itemsByPath[action.filePath]
                            } else {
                                console.error("Item already exists, can't move", action.newFilePath)
                            }
                        } else {
                            console.error("Item not found, can't move", action.filePath)
                        }
                    } else if (action.type === 'create' && action.newFilePath) {
                        if (!itemsByPath[action.newFilePath]) {
                            itemsByPath[action.newFilePath] = { ...action.item, path: action.newFilePath }
                        } else {
                            console.error("Item already exists, can't create", action.item)
                        }
                    } else if (action.type === 'delete' && action.filePath) {
                        delete itemsByPath[action.filePath]
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
                        if (action.newFilePath) {
                            unappliedPaths[action.newFilePath] = true
                            const split = action.newFilePath.split('/')
                            for (let i = 1; i < split.length; i++) {
                                unappliedPaths[split.slice(0, i).join('/')] = true
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
                    loadingPaths[pendingActions[0].newFilePath || pendingActions[0].filePath] = true
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
            (s) => [s.pendingActionsCount, s.pendingLoaderLoading, s.currentTeamName],
            (pendingActionsCount, pendingLoaderLoading, currentTeamName): TreeDataItem[] => [
                ...(pendingActionsCount > 0
                    ? [
                          {
                              id: 'applyPendingActions',
                              name: `--- Apply${
                                  pendingLoaderLoading ? 'ing' : ''
                              } ${pendingActionsCount} unsaved change${pendingActionsCount > 1 ? 's' : ''} ---`,
                              icon: pendingLoaderLoading ? <Spinner /> : <IconUpload className="text-warning" />,
                              onClick: !pendingLoaderLoading
                                  ? () => projectTreeLogic.actions.applyPendingActions()
                                  : undefined,
                              type: 'file' as const,
                              filePath: 'applyPendingActions',
                          },
                      ]
                    : [
                          {
                              id: '--',
                              name: '----------------------',
                              type: 'separator' as const,
                          },
                      ]),
                {
                    id: 'project',
                    name: currentTeamName,
                    icon: <IconBook />,
                    record: { type: 'project', id: 'project' },
                    onClick: () => router.actions.push(urls.projectHomepage()),
                    type: 'project' as const,
                    filePath: 'project',
                },
            ],
        ],
        treeData: [
            (s) => [s.defaultTreeNodes, s.projectTree, s.projectRow, s.loadingTree],
            (defaultTreeNodes, projectTree, projectRow, loadingTree): TreeDataItem[] => {
                return loadingTree
                    ? [
                          ...defaultTreeNodes,
                          ...projectRow,
                          {
                              id: '',
                              name: '',
                              type: 'loading' as const,
                              filePath: '',
                          },
                      ]
                    : [...defaultTreeNodes, ...projectRow, ...projectTree]
            },
        ],
        currentItemFromUrl: [
            (s) => [s.viableItems, router.selectors.location],
            (viableItems, location): FileSystemEntry | null => {
                const currentPath = location.pathname
                return (
                    viableItems.find((item) => {
                        if (item.href && currentPath.endsWith(item.href)) {
                            return item
                        }
                        return false
                    }) || null
                )
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        moveItem: async ({ oldFilePath, newFilePath }) => {
            for (const item of values.viableItems) {
                if (item.path === oldFilePath || item.path.startsWith(oldFilePath + '/')) {
                    actions.queueAction({
                        type: 'move',
                        item,
                        filePath: item.path,
                        newFilePath: newFilePath + item.path.slice(oldFilePath.length),
                    })
                }
            }
        },
        deleteItem: async ({ item }) => {
            actions.queueAction({ type: 'delete', item, filePath: item.path })
        },
        addFolder: ({ folder }) => {
            if (values.viableItems.find((item) => item.path === folder)) {
                return
            }
            actions.queueAction({
                type: 'create',
                item: { id: `project/${folder}`, path: folder, type: 'folder' },
                filePath: folder,
                newFilePath: folder,
            })
        },
        setExpandedFolders: ({ folders }) => {
            localStorage.setItem('posthog_project_tree_expanded', JSON.stringify(folders))
        },
        setActiveFolder: ({ folder }) => {
            localStorage.setItem('posthog_project_tree_active', folder || '')
        },
        setLastViewedPath: ({ path }) => {
            localStorage.setItem('posthog_project_tree_path', path)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSavedItems()
        actions.loadUnfiledItems('feature_flag')
        actions.loadUnfiledItems('experiment')
        actions.loadUnfiledItems('insight')
        actions.loadUnfiledItems('dashboard')
        actions.loadUnfiledItems('notebook')

        // Restore saved state
        const savedExpanded = localStorage.getItem('posthog_project_tree_expanded')
        const savedActive = localStorage.getItem('posthog_project_tree_active')
        const savedPath = localStorage.getItem('posthog_project_tree_path')

        if (savedExpanded) {
            actions.setExpandedFolders(JSON.parse(savedExpanded))
        }
        if (savedActive) {
            actions.setActiveFolder(savedActive)
        }
        if (savedPath) {
            actions.setLastViewedPath(savedPath)
        }
    }),
])
