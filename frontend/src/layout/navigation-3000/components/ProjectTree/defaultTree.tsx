import {
    IconBook,
    IconChevronRight,
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
import { urls } from 'scenes/urls'

import { FileSystemType } from '~/queries/schema/schema-general'
import { InsightType, PipelineStage, ReplayTabs } from '~/types'

import { FileSystemImport } from './types'

export function iconForType(type?: FileSystemType): JSX.Element {
    switch (type) {
        case 'aichat':
            return <IconSparkles />
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

export const getDefaultTree = (): FileSystemImport[] =>
    [
        {
            path: `Create new/AI chat`,
            type: 'aichat' as const,
            href: urls.max(),
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
            path: 'Explore/Data management',
            icon: <IconDatabase />,
            href: urls.eventDefinitions(),
        },
        {
            path: 'Explore/People and groups',
            icon: <IconPeople />,
            href: urls.persons(),
        },
        {
            path: 'Explore/Activity',
            icon: <IconLive />,
            href: urls.activity(),
        },
        {
            path: 'Explore/Web Analytics',
            icon: <IconPieChart />,
            href: urls.webAnalytics(),
        },
        {
            path: 'Explore/Recordings',
            href: urls.replay(ReplayTabs.Home),
            icon: <IconRewindPlay />,
        },
        {
            path: 'Explore/Playlists',
            href: urls.replay(ReplayTabs.Playlists),
            icon: <IconRewindPlay />,
        },
        {
            path: 'Explore/Error tracking',
            icon: <IconWarning />,
            href: urls.errorTracking(),
        },
        {
            path: 'Explore/Heatmaps',
            icon: <IconCursorClick />,
            href: urls.heatmaps(),
        },
    ].sort((a, b) => a.path.localeCompare(b.path))
