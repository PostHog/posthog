import {
    IconAI,
    IconBook,
    IconChevronRight,
    IconCursorClick,
    IconDatabase,
    IconFeatures,
    IconHandMoney,
    IconLive,
    IconMessage,
    IconNotification,
    IconPeople,
    IconPlug,
    IconServer,
    IconSparkles,
    IconWarning,
} from '@posthog/icons'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { fileSystemTypes, treeItemsExplore, treeItemsNew } from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'
import { ActivityTab, PipelineStage } from '~/types'

export function iconForType(type?: string): JSX.Element {
    if (!type) {
        return <IconBook />
    }
    if (type in fileSystemTypes && fileSystemTypes[type as keyof typeof fileSystemTypes].icon) {
        return fileSystemTypes[type as keyof typeof fileSystemTypes].icon
    }
    switch (type) {
        case 'aichat':
            return <IconSparkles />
        case 'feature':
            return <IconFeatures />
        case 'survey':
            return <IconMessage />
        case 'sql':
            return <IconServer />
        case 'folder':
            return <IconChevronRight />
        default:
            if (type.startsWith('hog_function/')) {
                return <IconPlug />
            }
            return <IconBook />
    }
}

export const getDefaultTreeNew = (): FileSystemImport[] =>
    [
        ...treeItemsNew,
        {
            path: `Early access feature`,
            type: 'early_access_feature',
            href: () => urls.earlyAccessFeature('new'),
        },
        {
            path: `Survey`,
            type: 'survey',
            href: () => urls.survey('new'),
        },
        {
            path: `Source`,
            type: 'hog_function/source',
            href: () => urls.pipelineNodeNew(PipelineStage.Source),
        },
        {
            path: `Destination`,
            type: 'hog_function/destination',
            href: () => urls.pipelineNodeNew(PipelineStage.Destination),
        },
        {
            path: `Transformation`,
            type: 'hog_function/transformation',
            href: () => urls.pipelineNodeNew(PipelineStage.Transformation),
        },
        {
            path: `Site app`,
            type: 'hog_function/site_app',
            href: () => urls.pipelineNodeNew(PipelineStage.SiteApp),
        },
    ].sort((a, b) => a.path.localeCompare(b.path))

export const getDefaultTreeExplore = (groupNodes: FileSystemImport[]): FileSystemImport[] =>
    [
        ...treeItemsExplore,
        {
            path: `AI chat`,
            type: 'aichat',
            href: () => urls.max(),
            flag: FEATURE_FLAGS.ARTIFICIAL_HOG,
        },
        {
            path: 'Data management/Event Definitions',
            icon: <IconDatabase />,
            href: () => urls.eventDefinitions(),
        },
        {
            path: 'Data management/Property Definitions',
            icon: <IconDatabase />,
            href: () => urls.propertyDefinitions(),
        },

        {
            path: 'Data management/Annotations',
            icon: <IconNotification />,
            href: () => urls.annotations(),
        },

        {
            path: 'Data management/History',
            icon: <IconDatabase />,
            href: () => urls.dataManagementHistory(),
        },

        {
            path: 'Data management/Revenue',
            icon: <IconHandMoney />,
            href: () => urls.revenueSettings(),
            flag: FEATURE_FLAGS.WEB_REVENUE_TRACKING,
        },
        {
            path: 'Data management/Ingestion Warnings',
            icon: <IconWarning />,
            href: () => urls.ingestionWarnings(),
            flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
        },
        {
            path: `SQL query`,
            type: 'sql',
            href: () => urls.sqlEditor(),
        },
        {
            path: 'Data warehouse',
            icon: <IconDatabase />,
            href: () => urls.sqlEditor(),
        },
        {
            path: 'People and groups/Cohorts',
            icon: <IconPeople />,
            href: () => urls.cohorts(),
        },
        ...groupNodes.map((groupNode) => ({ ...groupNode, path: `People and groups/${groupNode.path}` })),
        {
            path: 'Activity',
            icon: <IconLive />,
            href: () => urls.activity(ActivityTab.ExploreEvents),
        },
        {
            path: 'Live',
            icon: <IconLive />,
            href: () => urls.activity(ActivityTab.LiveEvents),
        },
        {
            path: 'LLM observability',
            icon: <IconAI />,
            href: () => urls.llmObservabilityDashboard(),
            flag: FEATURE_FLAGS.LLM_OBSERVABILITY,
        },
        {
            path: 'Error tracking',
            icon: <IconWarning />,
            href: () => urls.errorTracking(),
        },
        {
            path: 'Heatmaps',
            icon: <IconCursorClick />,
            href: () => urls.heatmaps(),
            flag: FEATURE_FLAGS.HEATMAPS_UI,
        },
    ].sort((a, b) => a.path.localeCompare(b.path))
