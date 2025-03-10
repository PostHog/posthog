import {
    IconAI,
    IconBook,
    IconCursorClick,
    IconDatabase,
    IconHandMoney,
    IconLive,
    IconNotification,
    IconPeople,
    IconPerson,
    IconPieChart,
    IconRewindPlay,
    IconRocket,
    IconWarning,
} from '@posthog/icons'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemType } from '~/queries/schema/schema-general'
import { ActivityTab, InsightType, PipelineStage, ReplayTabs } from '~/types'

import { fileSystemObjects } from './objects'
import { FileSystemImport } from './types'

export function iconForType(type?: FileSystemType): JSX.Element {
    return (type && fileSystemObjects[type]?.icon) ?? <IconBook />
}

export const getDefaultTree = (groupNodes: FileSystemImport[]): FileSystemImport[] =>
    [
        {
            path: `Create new/AI chat`,
            type: 'aichat' as const,
            href: urls.max(),
            flag: FEATURE_FLAGS.ARTIFICIAL_HOG,
        },
        {
            path: `Create new/Dashboard`,
            type: 'dashboard' as const,
            href: urls.dashboards() + '#newDashboard=modal',
        },
        {
            path: `Create new/Experiment`,
            type: 'experiment' as const,
            href: urls.experiment('new'),
        },
        {
            path: `Create new/Feature flag`,
            type: 'feature_flag' as const,
            href: urls.featureFlag('new'),
        },
        {
            path: `Create new/Feature`,
            type: 'feature' as const,
            href: urls.featureManagement('new'),
        },
        {
            path: `Create new/Insight/Trends`,
            type: 'insight' as const,
            href: urls.insightNew({ type: InsightType.TRENDS }),
        },
        {
            path: `Create new/Insight/Funnels`,
            type: 'insight' as const,
            href: urls.insightNew({ type: InsightType.FUNNELS }),
        },
        {
            path: `Create new/Insight/Retention`,
            type: 'insight' as const,
            href: urls.insightNew({ type: InsightType.RETENTION }),
        },
        {
            path: `Create new/Insight/User paths`,
            type: 'insight' as const,
            href: urls.insightNew({ type: InsightType.PATHS }),
        },
        {
            path: `Create new/Insight/Stickiness`,
            type: 'insight' as const,
            href: urls.insightNew({ type: InsightType.STICKINESS }),
        },
        {
            path: `Create new/Insight/Lifecycle`,
            type: 'insight' as const,
            href: urls.insightNew({ type: InsightType.LIFECYCLE }),
        },
        {
            path: `Create new/Notebook`,
            type: 'notebook' as const,
            href: urls.notebook('new'),
        },
        {
            path: `Create new/Broadcast`,
            type: 'broadcast' as const,
            href: urls.messagingBroadcasts(),
        },
        {
            path: `Create new/Repl`,
            type: 'repl' as const,
            href: urls.debugHog() + '#repl=[]&code=',
        },
        {
            path: `Create new/Survey`,
            type: 'survey' as const,
            href: urls.survey('new'),
        },
        {
            path: `Create new/SQL query`,
            type: 'sql' as const,
            href: urls.sqlEditor(),
        },
        {
            path: `Create new/Data pipeline/Source`,
            type: 'source' as const,
            href: urls.pipelineNodeNew(PipelineStage.Source),
        },
        {
            path: `Create new/Data pipeline/Destination`,
            type: 'destination' as const,
            href: urls.pipelineNodeNew(PipelineStage.Destination),
        },
        {
            path: `Create new/Data pipeline/Transformation`,
            type: 'transformation' as const,
            href: urls.pipelineNodeNew(PipelineStage.Transformation),
        },
        {
            path: `Create new/Data pipeline/Site app`,
            type: 'site_app' as const,
            href: urls.pipelineNodeNew(PipelineStage.SiteApp),
        },
        {
            path: 'Explore/Data management/Event Definitions',
            icon: <IconDatabase />,
            href: urls.eventDefinitions(),
        },
        {
            path: 'Explore/Data management/Actions',
            icon: <IconRocket />,
            href: urls.actions(),
        },

        {
            path: 'Explore/Data management/Property Definitions',
            icon: <IconDatabase />,
            href: urls.propertyDefinitions(),
        },

        {
            path: 'Explore/Data management/Annotations',
            icon: <IconNotification />,
            href: urls.annotations(),
        },

        {
            path: 'Explore/Data management/History',
            icon: <IconDatabase />,
            href: urls.dataManagementHistory(),
        },

        {
            path: 'Explore/Data management/Revenue',
            icon: <IconHandMoney />,
            href: urls.revenue(),
            flag: FEATURE_FLAGS.WEB_REVENUE_TRACKING,
        },
        {
            path: 'Explore/Data management/Ingestion Warnings',
            icon: <IconWarning />,
            href: urls.ingestionWarnings(),
            flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
        },

        {
            path: 'Explore/Data warehouse',
            icon: <IconDatabase />,
            href: urls.dataWarehouse(),
        },
        {
            path: 'Explore/People and groups/People',
            icon: <IconPerson />,
            href: urls.persons(),
        },
        {
            path: 'Explore/People and groups/Cohorts',
            icon: <IconPeople />,
            href: urls.cohorts(),
        },
        ...groupNodes.map((groupNode) => ({ ...groupNode, path: `Explore/People and groups/${groupNode.path}` })),
        {
            path: 'Explore/Activity',
            icon: <IconLive />,
            href: urls.activity(ActivityTab.ExploreEvents),
        },
        {
            path: 'Explore/Live',
            icon: <IconLive />,
            href: urls.activity(ActivityTab.LiveEvents),
        },
        {
            path: 'Explore/LLM ovservability',
            icon: <IconAI />,
            href: urls.llmObservabilityDashboard(),
            flag: FEATURE_FLAGS.LLM_OBSERVABILITY,
        },
        {
            path: 'Explore/Web Analytics',
            icon: <IconPieChart />,
            href: urls.webAnalytics(),
        },
        {
            path: 'Explore/Recordings/Recordings',
            href: urls.replay(ReplayTabs.Home),
            icon: <IconRewindPlay />,
        },
        {
            path: 'Explore/Recordings/What to watch',
            href: urls.replay(ReplayTabs.Templates),
            icon: <IconRewindPlay />,
        },
        {
            path: 'Explore/Recordings/Playlists',
            href: urls.replay(ReplayTabs.Playlists),
            icon: <IconRewindPlay />,
        },
        {
            path: 'Explore/Error tracking',
            icon: <IconWarning />,
            href: urls.errorTracking(),
            flag: FEATURE_FLAGS.ERROR_TRACKING,
        },
        {
            path: 'Explore/Early access features',
            icon: <IconRocket />,
            href: urls.earlyAccessFeatures(),
        },
        {
            path: 'Explore/Heatmaps',
            icon: <IconCursorClick />,
            href: urls.heatmaps(),
            flag: FEATURE_FLAGS.HEATMAPS_UI,
        },
    ].sort((a, b) => a.path.localeCompare(b.path))
