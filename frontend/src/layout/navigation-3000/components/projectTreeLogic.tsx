import {
    IconBook,
    IconCursorClick,
    IconDatabase,
    IconGraph,
    IconLive,
    IconMessage,
    IconNotebook,
    IconPeople,
    IconPieChart,
    IconPlug,
    IconRewindPlay,
    IconServer,
    IconSparkles,
    IconTarget,
    IconTestTube,
    IconToggle,
    IconWarning,
} from '@posthog/icons'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { notebooksTableLogic } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'

import { FileSystemEntry, FileSystemType } from '~/queries/schema'
import { InsightType, PipelineStage, ReplayTabs } from '~/types'

import type { projectTreeLogicType } from './projectTreeLogicType'

export interface ProjectTreeAction {
    type: 'move' | 'move-create' | 'create' | 'delete'
    item: FileSystemEntry
    path: string
    newPath?: string
}

export const getDefaultTree = (): TreeDataItem[] => [
    {
        id: 'new/',
        name: 'Create new',
        children: [
            {
                id: 'new/aichat',
                name: 'AI Chat',
                icon: <IconSparkles />,
                onClick: () => router.actions.push(urls.max()),
            },
            {
                id: 'new/dashboard',
                name: 'Dashboard',
                icon: iconForType('dashboard'),
                onClick: () => router.actions.push(urls.dashboards() + '#newDashboard=modal'),
            },
            {
                id: 'new/experiment',
                name: 'Experiment',
                icon: iconForType('experiment'),
                onClick: () => router.actions.push(urls.experiment('new')),
            },
            {
                id: 'new/feature_flag',
                name: 'Feature flag',
                icon: iconForType('feature_flag'),
                onClick: () => router.actions.push(urls.featureFlag('new')),
            },
            {
                id: 'new/insight',
                name: 'Insight',
                children: [
                    {
                        id: 'new/insight/trends',
                        name: 'Trends',
                        icon: iconForType('insight'),
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.TRENDS })),
                    },
                    {
                        id: 'new/insight/funnels',
                        name: 'Funnels',
                        icon: iconForType('insight'),
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.FUNNELS })),
                    },
                    {
                        id: 'new/insight/retention',
                        name: 'Retention',
                        icon: iconForType('insight'),
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.RETENTION })),
                    },
                    {
                        id: 'new/insight/paths',
                        name: 'User Paths',
                        icon: iconForType('insight'),
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.PATHS })),
                    },
                    {
                        id: 'new/insight/stickiness',
                        name: 'Stickiness',
                        icon: iconForType('insight'),
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.STICKINESS })),
                    },
                    {
                        id: 'new/insight/lifecycle',
                        name: 'Lifecycle',
                        icon: iconForType('insight'),
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.LIFECYCLE })),
                    },
                ],
            },
            {
                id: 'new/notebook',
                name: 'Notebook',
                icon: iconForType('notebook'),
                onClick: () => router.actions.push(urls.notebook('new')),
            },
            {
                id: 'new/repl',
                name: 'Repl',
                icon: iconForType('repl'),
                onClick: () => router.actions.push(urls.debugHog() + '#repl=[]&code='),
            },
            {
                id: 'new/survey',
                name: 'Survey',
                icon: iconForType('survey'),
                onClick: () => router.actions.push(urls.experiment('new')),
            },
            {
                id: 'new/sql',
                name: 'SQL query',
                icon: iconForType('sql'),
                onClick: () => router.actions.push(urls.sqlEditor()),
            },
            {
                id: 'new/pipeline',
                name: 'Data pipeline',
                icon: <IconPlug />,
                children: [
                    {
                        id: 'new/pipeline/source',
                        name: 'Source',
                        icon: iconForType('source'),
                        onClick: () => router.actions.push(urls.pipelineNodeNew(PipelineStage.Source)),
                    },
                    {
                        id: 'new/pipeline/destination',
                        name: 'Destination',
                        icon: iconForType('destination'),
                        onClick: () => router.actions.push(urls.pipelineNodeNew(PipelineStage.Destination)),
                    },
                    {
                        id: 'new/pipeline/transformation',
                        name: 'Transformation',
                        icon: iconForType('transformation'),
                        onClick: () => router.actions.push(urls.pipelineNodeNew(PipelineStage.Transformation)),
                    },
                    {
                        id: 'new/pipeline/site_app',
                        name: 'Site App',
                        icon: iconForType('site_app'),
                        onClick: () => router.actions.push(urls.pipelineNodeNew(PipelineStage.SiteApp)),
                    },
                ],
            },
        ].sort((a, b) => a.name.localeCompare(b.name)),
    },
    {
        id: 'explore',
        name: 'Explore data',
        icon: <IconDatabase />,
        children: [
            {
                id: 'explore/data_management',
                name: 'Data management',
                icon: <IconDatabase />,
                onClick: () => router.actions.push(urls.eventDefinitions()),
            },
            {
                id: 'explore/people_and_groups',
                name: 'People and groups',
                icon: <IconPeople />,
                onClick: () => router.actions.push(urls.persons()),
            },
            {
                id: 'explore/activity',
                name: 'Activity',
                icon: <IconLive />,
                onClick: () => router.actions.push(urls.activity()),
            },
            {
                id: 'explore/web_analytics',
                name: 'Web Analytics',
                icon: <IconPieChart />,
                onClick: () => router.actions.push(urls.webAnalytics()),
            },
            {
                id: 'explore/recordings',
                name: 'Recordings',
                onClick: () => router.actions.push(urls.replay(ReplayTabs.Home)),
                icon: <IconRewindPlay />,
            },
            {
                id: 'explore/playlists',
                name: 'Playlists',
                onClick: () => router.actions.push(urls.replay(ReplayTabs.Playlists)),
                icon: <IconRewindPlay />,
            },
            {
                id: 'explore/error_tracking',
                name: 'Error tracking',
                icon: <IconWarning />,
                onClick: () => router.actions.push(urls.errorTracking()),
            },
            {
                id: 'explore/heatmaps',
                name: 'Heatmaps',
                icon: <IconCursorClick />,
                onClick: () => router.actions.push(urls.heatmaps()),
            },
        ].sort((a, b) => a.name.localeCompare(b.name)),
    },
]

export function iconForType(type?: FileSystemType): JSX.Element {
    switch (type) {
        case 'feature_flag':
            return <IconToggle />
        case 'experiment':
            return <IconTestTube />
        case 'insight':
            return <IconGraph />
        case 'notebook':
            return <IconNotebook />
        case 'dashboard':
            return <IconGraph />
        case 'repl':
            return <IconTarget />
        case 'survey':
            return <IconMessage />
        case 'sql':
            return <IconServer />
        case 'site_app':
            return <IconPlug />
        case 'destination':
            return <IconPlug />
        case 'transformation':
            return <IconPlug />
        case 'source':
            return <IconPlug />
        case 'folder':
            return <IconChevronRight />
        default:
            return <IconBook />
    }
}

export const projectTreeLogic = kea<projectTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'projectTreeLogic']),
    connect(() => ({
        values: [
            featureFlagsLogic,
            ['featureFlags'],
            savedInsightsLogic,
            ['insights'],
            experimentsLogic,
            ['experiments'],
            dashboardsLogic,
            ['dashboards'],
            notebooksTableLogic,
            ['notebooks'],
        ],
        actions: [notebooksTableLogic, ['loadNotebooks']],
    })),
    actions({
        loadFiledItems: true,
        loadUnfiledItems: true,
        addFolder: (folder: string) => ({ folder }),
        renameItem: (oldName: string, newName: string) => ({ oldName, newName }),
        createItem: (item: FileSystemEntry) => ({ item }),
        deleteItem: (item: FileSystemEntry) => ({ item }),
        moveItem: (oldPath: string, newPath: string) => ({ oldPath, newPath }),
        queueAction: (action: ProjectTreeAction) => ({ action }),
        removeQueuedAction: (action: ProjectTreeAction) => ({ action }),
    }),
    loaders({
        savedItems: [
            [] as FileSystemEntry[],
            {
                loadFiledItems: async () => {
                    const response = await api.fileSystem.list()
                    return response.results
                },
            },
        ],
        allUnfiledItems: [
            [] as FileSystemEntry[],
            {
                loadUnfiledItems: async () => {
                    const response = await api.fileSystem.unfiled()
                    return response.results
                },
            },
        ],
    }),
    reducers({
        pendingActions: [
            [] as ProjectTreeAction[],
            {
                queueAction: (state, { action }) => [...state, action],
                removeQueuedAction: (state, { action }) => state.filter((a) => a !== action),
            },
        ],
    }),
    selectors({
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
                    }
                }
                return Object.values(itemsByPath)
            },
        ],
        loadingPaths: [
            // Paths that are currently being loaded
            (s) => [s.pendingActions, s.allUnfiledItemsLoading, s.savedItemsLoading],
            (pendingActions, allUnfiledItemsLoading, savedItemsLoading) => {
                const loadingPaths: Record<string, boolean> = {}
                for (const action of pendingActions) {
                    if (action.type === 'move-create' || action.type === 'move' || action.type === 'create') {
                        if (action.newPath) {
                            loadingPaths[action.newPath] = true
                            const split = action.newPath.split('/')
                            for (let i = 1; i < split.length; i++) {
                                loadingPaths[split.slice(0, i).join('/')] = true
                            }
                        }
                    }
                }
                if (allUnfiledItemsLoading) {
                    loadingPaths['Unfiled'] = true
                    loadingPaths[''] = true
                }
                if (savedItemsLoading) {
                    loadingPaths[''] = true
                }
                return loadingPaths
            },
        ],
        projectTree: [
            (s) => [s.viableItems],
            (viableItems): TreeDataItem[] => {
                // The top-level nodes for our project tree
                const rootNodes: TreeDataItem[] = []

                // Helper to find an existing folder node or create one if it doesn't exist.
                const findOrCreateFolder = (
                    nodes: TreeDataItem[],
                    folderName: string,
                    fullPath: string
                ): TreeDataItem => {
                    let folderNode = nodes.find((node) => node.data.path === fullPath)
                    if (!folderNode) {
                        folderNode = {
                            id: 'project/' + fullPath,
                            name: folderName,
                            data: { type: 'folder', id: 'project/' + fullPath, path: fullPath },
                            children: [],
                        }
                        nodes.push(folderNode)
                    }
                    if (!folderNode.children) {
                        folderNode.children = []
                    }
                    return folderNode
                }

                // Iterate over each raw project item.
                for (const item of viableItems) {
                    const pathSplit = item.path.split('/').filter(Boolean)
                    const itemName = pathSplit.pop()!
                    const folderPath = pathSplit.join('/')

                    // Split the folder path by "/" (ignoring empty parts).
                    const folderParts = folderPath ? folderPath.split('/').filter(Boolean) : []

                    // Start at the root level.
                    let currentLevel = rootNodes
                    let accumulatedPath = ''

                    // Create (or find) nested folders as needed.
                    for (const part of folderParts) {
                        accumulatedPath = accumulatedPath ? accumulatedPath + '/' + part : part
                        const folderNode = findOrCreateFolder(currentLevel, part, accumulatedPath)
                        currentLevel = folderNode.children!
                    }

                    if (item.type === 'folder' && currentLevel.find((node) => node.data.path === item.path)) {
                        continue
                    }

                    // Create the actual item node.
                    const node: TreeDataItem = {
                        id: 'project/' + item.id,
                        name: itemName,
                        icon: iconForType(item.type),
                        data: item,
                        onClick: () => {
                            if (item.href) {
                                router.actions.push(item.href)
                            }
                        },
                    }
                    // Place the item in the current (deepest) folder.
                    currentLevel.push(node)
                }

                // Helper function to sort nodes (and their children) alphabetically by name.
                const sortNodes = (nodes: TreeDataItem[]): void => {
                    nodes.sort((a, b) => a.name.localeCompare(b.name))
                    for (const node of nodes) {
                        if (node.children) {
                            sortNodes(node.children)
                        }
                    }
                }
                sortNodes(rootNodes)
                return rootNodes
            },
        ],
        defaultTreeNodes: [() => [], (): TreeDataItem[] => getDefaultTree()],
        projectRow: [
            () => [],
            (): TreeDataItem[] => [
                {
                    id: 'project',
                    name: 'Default Project',
                    icon: <IconBook />,
                    data: { type: 'project', id: 'project' },
                    onClick: () => router.actions.push(urls.projectHomepage()),
                },
            ],
        ],
        treeData: [
            (s) => [s.defaultTreeNodes, s.projectTree, s.projectRow],
            (defaultTreeNodes, projectTree, projectRow): TreeDataItem[] => {
                return [
                    ...defaultTreeNodes,
                    {
                        id: '--',
                        name: '-----------',
                    },
                    ...projectRow,
                    ...projectTree,
                ]
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        moveItem: async ({ oldPath, newPath }) => {
            // rename all filed items
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
    })),
    afterMount(({ actions }) => {
        actions.loadFiledItems()
        actions.loadUnfiledItems()
        actions.loadNotebooks()
    }),
])
