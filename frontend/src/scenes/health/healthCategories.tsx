import { IconCode, IconDatabase, IconPulse, IconWarning } from '@posthog/icons'

export type HealthIssueCategory = 'ingestion' | 'sdk' | 'pipelines' | 'other'

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
    pipelines: {
        label: 'Pipelines',
        description: 'Data pipelines and transformations',
        healthyDescription: 'All healthy',
        icon: <IconDatabase className="size-5" />,
        showInSummary: true,
    },
    other: {
        label: 'Other',
        description: 'Other health issues',
        icon: <IconWarning className="size-5" />,
        showInSummary: false,
    },
}

const KIND_TO_CATEGORY: Record<string, HealthIssueCategory> = {
    // Ingestion
    no_live_events: 'ingestion',
    ingestion_lag: 'ingestion',

    // SDKs
    sdk_outdated: 'sdk',
}

export const KIND_LABELS: Record<string, string> = {
    no_live_events: 'No live events',
    ingestion_lag: 'Ingestion lag',
    sdk_outdated: 'SDK outdated',
}

export const categoryForKind = (kind: string): HealthIssueCategory => {
    return KIND_TO_CATEGORY[kind] ?? 'other'
}

export const CATEGORY_ORDER: HealthIssueCategory[] = ['ingestion', 'sdk', 'pipelines', 'other']
