import {
    IconAI,
    IconBook,
    IconChevronRight,
    IconCursorClick,
    IconDatabase,
    IconHandMoney,
    IconLive,
    IconNotification,
    IconPieChart,
    IconPiggyBank,
    IconPlug,
    IconServer,
    IconWarning,
} from '@posthog/icons'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import {
    fileSystemTypes,
    getTreeItemsDataManagement,
    getTreeItemsGames,
    getTreeItemsNew,
    getTreeItemsProducts,
} from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'
import { ActivityTab, PipelineStage } from '~/types'

const iconTypes: Record<string, JSX.Element> = {
    ai: <IconAI />,
    cursorClick: <IconCursorClick />,
    database: <IconDatabase />,
    folder: <IconChevronRight />,
    handMoney: <IconHandMoney />,
    live: <IconLive />,
    notification: <IconNotification />,
    pieChart: <IconPieChart />,
    piggyBank: <IconPiggyBank />,
    plug: <IconPlug />,
    sql: <IconServer />,
    warning: <IconWarning />,
}

export function iconForType(type?: string): JSX.Element {
    if (!type) {
        return <IconBook />
    }
    if (type in iconTypes) {
        return iconTypes[type]
    }
    if (type in fileSystemTypes && fileSystemTypes[type].icon) {
        return fileSystemTypes[type].icon
    }
    if (type.startsWith('hog_function/')) {
        return <IconPlug />
    }
    return <IconBook />
}

export const getDefaultTreeNew = (): FileSystemImport[] =>
    [
        ...getTreeItemsNew(),
        {
            path: `Data/Source`,
            type: 'hog_function/source',
            href: urls.pipelineNodeNew(PipelineStage.Source),
        },
        {
            path: `Data/Destination`,
            type: 'hog_function/destination',
            href: urls.pipelineNodeNew(PipelineStage.Destination),
        },
        {
            path: `Data/Transformation`,
            type: 'hog_function/transformation',
            href: urls.pipelineNodeNew(PipelineStage.Transformation),
        },
        {
            path: `Data/Site app`,
            type: 'hog_function/site_app',
            href: urls.pipelineNodeNew(PipelineStage.SiteApp),
        },
    ].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))

export const getDefaultTreeDataManagement = (): FileSystemImport[] => [
    ...getTreeItemsDataManagement(),
    {
        path: 'Event definitions',
        iconType: 'database',
        href: urls.eventDefinitions(),
    },
    {
        path: 'Property definitions',
        iconType: 'database',
        href: urls.propertyDefinitions(),
    },
    {
        path: 'Annotations',
        iconType: 'notification',
        href: urls.annotations(),
    },
    {
        path: 'Ingestion warnings',
        iconType: 'warning',
        href: urls.ingestionWarnings(),
        flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
    },
]

export const getDefaultTreeProducts = (): FileSystemImport[] =>
    [
        ...getTreeItemsProducts(),
        {
            path: `AI chat`,
            type: 'aichat',
            href: urls.max(),
            flag: FEATURE_FLAGS.ARTIFICIAL_HOG,
        },
        {
            path: `Data pipelines`,
            type: 'hog_function',
            iconType: 'plug',
            href: urls.pipeline(),
        },
        {
            path: `SQL editor`,
            type: 'sql',
            href: urls.sqlEditor(),
        },
        {
            path: 'Data warehouse',
            iconType: 'database',
            href: urls.sqlEditor(),
        },
        {
            path: 'Live events',
            iconType: 'live',
            href: urls.activity(ActivityTab.LiveEvents),
        },
        {
            path: 'Error tracking',
            iconType: 'warning',
            href: urls.errorTracking(),
        },
        {
            path: 'Heatmaps',
            iconType: 'cursorClick',
            href: urls.heatmaps(),
            flag: FEATURE_FLAGS.HEATMAPS_UI,
        },
    ].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))

export const getDefaultTreeGames = (): FileSystemImport[] =>
    [...getTreeItemsGames()].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))
