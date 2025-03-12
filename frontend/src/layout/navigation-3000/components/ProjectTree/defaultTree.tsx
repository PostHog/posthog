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
    IconRocket,
    IconServer,
    IconSparkles,
    IconTarget,
    IconWarning,
} from '@posthog/icons'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { fileSystemTypes, treeItems } from '~/products'
import { FileSystemType } from '~/queries/schema/schema-general'
import { ActivityTab, PipelineStage } from '~/types'

import { FileSystemImport } from './types'

export function iconForType(type?: FileSystemType): JSX.Element {
    if (type && type in fileSystemTypes && (fileSystemTypes as any)[type].icon) {
        return (fileSystemTypes as any)[type].icon
    }
    switch (type) {
        case 'aichat':
            return <IconSparkles />
        case 'feature':
            return <IconFeatures />
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

export const getDefaultTree = (groupNodes: FileSystemImport[]): FileSystemImport[] =>
    [
        ...treeItems,
        {
            path: `Create new/AI chat`,
            type: 'aichat' as const,
            href: () => urls.max(),
            flag: FEATURE_FLAGS.ARTIFICIAL_HOG,
        },
        {
            path: `Create new/Feature`,
            type: 'feature' as const,
            href: () => urls.featureManagement('new'),
        },
        {
            path: `Create new/Repl`,
            type: 'repl' as const,
            href: () => urls.debugHog() + '#repl=[]&code=',
        },
        {
            path: `Create new/Survey`,
            type: 'survey' as const,
            href: () => urls.survey('new'),
        },
        {
            path: `Create new/SQL query`,
            type: 'sql' as const,
            href: () => urls.sqlEditor(),
        },
        {
            path: `Create new/Data pipeline/Source`,
            type: 'source' as const,
            href: () => urls.pipelineNodeNew(PipelineStage.Source),
        },
        {
            path: `Create new/Data pipeline/Destination`,
            type: 'destination' as const,
            href: () => urls.pipelineNodeNew(PipelineStage.Destination),
        },
        {
            path: `Create new/Data pipeline/Transformation`,
            type: 'transformation' as const,
            href: () => urls.pipelineNodeNew(PipelineStage.Transformation),
        },
        {
            path: `Create new/Data pipeline/Site app`,
            type: 'site_app' as const,
            href: () => urls.pipelineNodeNew(PipelineStage.SiteApp),
        },
        {
            path: 'Explore/Data management/Event Definitions',
            icon: <IconDatabase />,
            href: () => urls.eventDefinitions(),
        },
        {
            path: 'Explore/Data management/Actions',
            icon: <IconRocket />,
            href: () => urls.actions(),
        },

        {
            path: 'Explore/Data management/Property Definitions',
            icon: <IconDatabase />,
            href: () => urls.propertyDefinitions(),
        },

        {
            path: 'Explore/Data management/Annotations',
            icon: <IconNotification />,
            href: () => urls.annotations(),
        },

        {
            path: 'Explore/Data management/History',
            icon: <IconDatabase />,
            href: () => urls.dataManagementHistory(),
        },

        {
            path: 'Explore/Data management/Revenue',
            icon: <IconHandMoney />,
            href: () => urls.revenue(),
            flag: FEATURE_FLAGS.WEB_REVENUE_TRACKING,
        },
        {
            path: 'Explore/Data management/Ingestion Warnings',
            icon: <IconWarning />,
            href: () => urls.ingestionWarnings(),
            flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
        },

        {
            path: 'Explore/Data warehouse',
            icon: <IconDatabase />,
            href: () => urls.dataWarehouse(),
        },
        {
            path: 'Explore/People and groups/Cohorts',
            icon: <IconPeople />,
            href: () => urls.cohorts(),
        },
        ...groupNodes.map((groupNode) => ({ ...groupNode, path: `Explore/People and groups/${groupNode.path}` })),
        {
            path: 'Explore/Activity',
            icon: <IconLive />,
            href: () => urls.activity(ActivityTab.ExploreEvents),
        },
        {
            path: 'Explore/Live',
            icon: <IconLive />,
            href: () => urls.activity(ActivityTab.LiveEvents),
        },
        {
            path: 'Explore/LLM ovservability',
            icon: <IconAI />,
            href: () => urls.llmObservabilityDashboard(),
            flag: FEATURE_FLAGS.LLM_OBSERVABILITY,
        },
        {
            path: 'Explore/Error tracking',
            icon: <IconWarning />,
            href: () => urls.errorTracking(),
            flag: FEATURE_FLAGS.ERROR_TRACKING,
        },
        {
            path: 'Explore/Heatmaps',
            icon: <IconCursorClick />,
            href: () => urls.heatmaps(),
            flag: FEATURE_FLAGS.HEATMAPS_UI,
        },
    ].sort((a, b) => a.path.localeCompare(b.path))
