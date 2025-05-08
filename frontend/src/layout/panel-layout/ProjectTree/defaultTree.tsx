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

import { fileSystemTypes, treeItemsAllProducts, treeItemsNew } from '~/products'
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
            path: `Cohort`,
            type: 'cohort',
            href: () => urls.cohort('new'),
        },
        {
            path: `Data/Source`,
            type: 'hog_function/source',
            href: () => urls.pipelineNodeNew(PipelineStage.Source),
        },
        {
            path: `Data/Destination`,
            type: 'hog_function/destination',
            href: () => urls.pipelineNodeNew(PipelineStage.Destination),
        },
        {
            path: `Data/Transformation`,
            type: 'hog_function/transformation',
            href: () => urls.pipelineNodeNew(PipelineStage.Transformation),
        },
        {
            path: `Data/Site app`,
            type: 'hog_function/site_app',
            href: () => urls.pipelineNodeNew(PipelineStage.SiteApp),
        },
    ].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))

export const getDefaultTreeExplore = (): FileSystemImport[] =>
    [
        ...treeItemsAllProducts,
        {
            path: `AI chat`,
            type: 'aichat',
            href: () => urls.max(),
            flag: FEATURE_FLAGS.ARTIFICIAL_HOG,
        },
        {
            path: 'Event definitions',
            icon: <IconDatabase />,
            href: () => urls.eventDefinitions(),
        },
        {
            path: 'Property definitions',
            icon: <IconDatabase />,
            href: () => urls.propertyDefinitions(),
        },
        {
            path: 'Annotations',
            icon: <IconNotification />,
            href: () => urls.annotations(),
        },
        {
            path: 'Revenue',
            icon: <IconHandMoney />,
            href: () => urls.revenueSettings(),
        },
        {
            path: 'Ingestion warnings',
            icon: <IconWarning />,
            href: () => urls.ingestionWarnings(),
            flag: FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED,
        },
        {
            path: `Data pipelines`,
            type: 'hog_function',
            icon: <IconPlug />,
            href: () => urls.pipeline(),
        },
        {
            path: `SQL editor`,
            type: 'sql',
            href: () => urls.sqlEditor(),
        },
        {
            path: 'Data warehouse',
            icon: <IconDatabase />,
            href: () => urls.sqlEditor(),
        },
        {
            path: 'Cohorts',
            icon: <IconPeople />,
            href: () => urls.cohorts(),
        },
        {
            path: 'Group analytics',
            icon: <IconPeople />,
            href: () => urls.groups(0),
        },
        {
            path: 'Activity',
            icon: <IconLive />,
            href: () => urls.activity(ActivityTab.ExploreEvents),
        },
        {
            path: 'Live events',
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
        {
            path: 'Surveys',
            icon: <IconMessage />,
            href: () => urls.surveys(),
        },
    ].sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' }))
