import { IconCode, IconDatabase, IconDecisionTree, IconPulse, IconTrending, IconWarning } from '@posthog/icons'

export type HealthIssueCategory = 'ingestion' | 'sdk' | 'web_analytics' | 'data_modeling' | 'pipelines' | 'other'

export type HealthIssueKind =
    | 'no_live_events'
    | 'no_pageleave_events'
    | 'scroll_depth'
    | 'authorized_urls'
    | 'reverse_proxy'
    | 'web_vitals'
    | 'ingestion_lag'
    | 'sdk_outdated'
    | 'materialized_view_failure'

interface CategoryConfig {
    label: string
    description: string
    healthyDescription?: string
    icon: JSX.Element
    showInSummary: boolean
}

export const HEALTH_CATEGORY_CONFIG: Record<HealthIssueCategory, CategoryConfig> = {
    ingestion: {
        label: 'Ingestion',
        description: 'Event ingestion and data collection',
        healthyDescription: 'Events flowing normally',
        icon: <IconPulse className="size-5" />,
        showInSummary: true,
    },
    sdk: {
        label: 'SDKs',
        description: 'SDK versions and configuration',
        healthyDescription: 'Up to date',
        icon: <IconCode className="size-5" />,
        showInSummary: true,
    },
    web_analytics: {
        label: 'Web analytics',
        description: 'Web analytics setup and configuration',
        healthyDescription: 'Setup looks good',
        icon: <IconTrending className="size-5" />,
        showInSummary: true,
    },
    pipelines: {
        label: 'Pipelines',
        description: 'Data pipelines and transformations',
        healthyDescription: 'All healthy',
        icon: <IconDatabase className="size-5" />,
        showInSummary: true,
    },
    data_modeling: {
        label: 'Data modeling',
        description: 'Materialized views and data models',
        healthyDescription: 'All healthy',
        icon: <IconDecisionTree className="size-5" />,
        showInSummary: true,
    },
    other: {
        label: 'Other',
        description: 'Other health issues',
        icon: <IconWarning className="size-5" />,
        showInSummary: false,
    },
}

const KIND_TO_CATEGORY: Record<HealthIssueKind, HealthIssueCategory> = {
    // Ingestion
    ingestion_lag: 'ingestion',

    // Data modeling
    materialized_view_failure: 'data_modeling',

    // SDKs
    sdk_outdated: 'sdk',

    // Web analytics
    no_live_events: 'web_analytics',
    no_pageleave_events: 'web_analytics',
    scroll_depth: 'web_analytics',
    authorized_urls: 'web_analytics',
    reverse_proxy: 'web_analytics',
    web_vitals: 'web_analytics',
}

export const KIND_LABELS: Record<HealthIssueKind, string> = {
    no_live_events: 'No live events',
    no_pageleave_events: 'No pageleave events',
    scroll_depth: 'No scroll depth tracking',
    authorized_urls: 'No authorized URLs',
    reverse_proxy: 'No reverse proxy',
    web_vitals: 'No web vitals',
    ingestion_lag: 'Ingestion lag',
    sdk_outdated: 'SDK outdated',
    materialized_view_failure: 'Materialized view failure',
}

export const categoryForKind = (kind: string): HealthIssueCategory => {
    return KIND_TO_CATEGORY[kind as HealthIssueKind] ?? 'other'
}

export const CATEGORY_ORDER: HealthIssueCategory[] = [
    'ingestion',
    'sdk',
    'web_analytics',
    'data_modeling',
    'pipelines',
    'other',
]
