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
    IconRocket,
    IconServer,
    IconSparkles,
    IconTarget,
    IconTestTube,
    IconToggle,
    IconWarning,
} from '@posthog/icons'
import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { uuid } from 'lib/utils'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { notebooksTableLogic } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { NodeKind, ProjectTreeItem, ProjectTreeItemType, ProjectTreeQuery } from '~/queries/schema'
import { InsightType, PipelineStage, ReplayTabs } from '~/types'

import type { projectTreeLogicType } from './projectTreeLogicType'

const testTreeData: TreeDataItem[] = [
    {
        id: 'gt_7d8f9j',
        name: 'Team DevEx',
        children: [
            {
                id: 'ssc_3d4e5jh',
                name: 'Hog Pivot Table',
                icon: <IconRocket />,
                onClick: () => router.actions.push(urls.debugHog()),
            },
            {
                id: 'ssc_3d4e5j4',
                name: 'Sparklines',
                icon: <IconTarget />,
                onClick: () => router.actions.push(urls.debugHog()),
            },
        ],
    },
    {
        id: 'gt_7d8f9',
        name: 'Team Growth',
        children: [
            {
                id: 'ssc_3d4e5',
                name: 'Self-serve credits',
                icon: <IconGraph />,
                disabledReason: "you're not cool enough",
            },
            {
                id: 'ot_f6g7h',
                name: 'Onboarding things',
                children: [
                    {
                        id: 'cf_8i9j0',
                        name: 'Conversion funnel',
                        icon: <IconGraph />,
                    },
                    {
                        id: 'mpu_k1l2m',
                        name: 'Multi-product usage',
                        icon: <IconGraph />,
                    },
                    {
                        id: 'pis_n3o4p',
                        name: 'Post-install survey',
                        icon: <IconGraph />,
                    },
                ],
            },
        ],
    },
]

export function iconForType(type?: ProjectTreeItemType): JSX.Element {
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
        loadProjectTree: true,
        addFolder: (folder: string) => ({ folder }),
        renameItem: (oldName: string, newName: string) => ({ oldName, newName }),
    }),
    loaders({
        rawProjectTree: [
            [] as ProjectTreeItem[],
            {
                loadProjectTree: async () => {
                    const response = await performQuery<ProjectTreeQuery>({ kind: NodeKind.ProjectTreeQuery })
                    return response.results
                },
            },
        ],
    }),
    reducers({
        customProjectTree: [
            [] as ProjectTreeItem[],
            {
                addFolder: (state, { folder }) => {
                    const splitFolder = folder.split('/')
                    return [
                        ...state,
                        {
                            id: uuid(),
                            name: splitFolder[splitFolder.length - 1],
                            folder: splitFolder.slice(0, -1).join('/'),
                            type: 'folder',
                            meta: {},
                        },
                    ]
                },
                renameItem: (state, { oldName, newName }) => {
                    return state.map((item) => {
                        const itemName = (item.folder ? item.folder + '/' : '') + item.name
                        if (itemName === oldName) {
                            const splitName = newName.split('/')
                            return {
                                ...item,
                                name: splitName[splitName.length - 1],
                                folder: splitName.slice(0, -1).join('/'),
                            }
                        } else if (itemName.startsWith(oldName + '/')) {
                            const fullNewName = newName + itemName.slice(oldName.length)
                            const splitName = fullNewName.split('/')
                            return {
                                ...item,
                                name: splitName[splitName.length - 1],
                                folder: splitName.slice(0, -1).join('/'),
                            }
                        }
                        return item
                    })
                },
            },
        ],
    }),
    selectors({
        takenUrls: [
            (s) => [s.rawProjectTree, s.customProjectTree],
            (rawProjectTree, customProjectTree) => {
                const urls = new Set<string>()
                for (const item of [...rawProjectTree, ...customProjectTree]) {
                    if (item.href) {
                        urls.add(item.href)
                    }
                }
                return urls
            },
        ],
        projectTree: [
            (s) => [s.rawProjectTree, s.customProjectTree],
            (rawProjectTree, customProjectTree): TreeDataItem[] => {
                // The top-level nodes for our project tree
                const rootNodes: TreeDataItem[] = []

                // Helper to find an existing folder node or create one if it doesn't exist.
                const findOrCreateFolder = (
                    nodes: TreeDataItem[],
                    folderName: string,
                    fullPath: string
                ): TreeDataItem => {
                    const folderPath = fullPath.split('/').slice(0, -1).join('/')
                    let folderNode = nodes.find(
                        (node) => node.data.folder == folderPath && node.data.name === folderName
                    )
                    if (!folderNode) {
                        folderNode = {
                            id: 'project/' + fullPath,
                            name: folderName,
                            data: { type: 'folder', id: 'project/' + fullPath, name: folderName, folder: folderPath },
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
                for (const item of [...rawProjectTree, ...customProjectTree]) {
                    // Get the folder string; if empty, the item goes at the root.
                    const folderPath = item.folder || ''
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

                    // Create the actual item node.
                    const node: TreeDataItem = {
                        id: 'project/' + item.id,
                        name: item.name,
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
        defaultTreeNodes: [
            () => [],
            (): TreeDataItem[] => [
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
                                    onClick: () =>
                                        router.actions.push(urls.insightNew({ type: InsightType.RETENTION })),
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
                                    onClick: () =>
                                        router.actions.push(urls.insightNew({ type: InsightType.STICKINESS })),
                                },
                                {
                                    id: 'new/insight/lifecycle',
                                    name: 'Lifecycle',
                                    icon: iconForType('insight'),
                                    onClick: () =>
                                        router.actions.push(urls.insightNew({ type: InsightType.LIFECYCLE })),
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
                                    onClick: () =>
                                        router.actions.push(urls.pipelineNodeNew(PipelineStage.Transformation)),
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
            ],
        ],
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
                    ...testTreeData,
                    ...projectTree,
                ]
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadProjectTree()
        actions.loadNotebooks()
    }),
])
