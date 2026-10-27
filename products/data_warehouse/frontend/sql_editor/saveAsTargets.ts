import type { ComponentType } from 'react'

import { IconCalculator, IconDatabase, IconEndpoints, IconGraph } from '@posthog/icons'

export type SaveAsTargetId = 'insight' | 'view' | 'endpoint' | 'metric'

export interface SaveAsTargetMetadata {
    label: string
    description: string
    helpText: string
    docsUrl: string
    icon: ComponentType<{ className?: string }>
}

export interface SaveAsTarget extends SaveAsTargetMetadata {
    id: SaveAsTargetId
    recommended: boolean
    disabledReason?: string | null
    dataAttr?: string
}

export interface SaveAsMenuProps {
    targets: SaveAsTarget[]
    onSelect: (target: SaveAsTargetId) => void
}

export const SAVE_AS_TARGETS: Record<SaveAsTargetId, SaveAsTargetMetadata> = {
    insight: {
        label: 'Insight',
        description: 'Visualize and share the query results.',
        helpText: 'Create a chart or table that you can share or add to a dashboard.',
        docsUrl: 'https://posthog.com/docs/data-warehouse/query#sql-visualizations',
        icon: IconGraph,
    },
    view: {
        label: 'View',
        description: 'Reuse the query results in other SQL queries.',
        helpText: 'Create a table that other SQL queries can use. You can materialize the view after you save it.',
        docsUrl: 'https://posthog.com/docs/data-warehouse/views',
        icon: IconDatabase,
    },
    endpoint: {
        label: 'Endpoint',
        description: 'Make the query available through an API.',
        helpText: 'Create a versioned API that runs this query and returns its results.',
        docsUrl: 'https://posthog.com/docs/endpoints',
        icon: IconEndpoints,
    },
    metric: {
        label: 'Metric',
        description: 'Define a reusable business measure.',
        helpText: 'Create a governed measure that people and tools can use from one shared definition.',
        docsUrl: 'https://posthog.com/docs/semantic-layer/metrics',
        icon: IconCalculator,
    },
}
