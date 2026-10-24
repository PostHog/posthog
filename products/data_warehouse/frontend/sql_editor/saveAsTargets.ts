import type { ComponentType } from 'react'

import { IconCalculator, IconDatabase, IconEndpoints, IconGraph } from '@posthog/icons'

export type SaveAsTargetId = 'insight' | 'view' | 'endpoint' | 'metric'

export interface SaveAsTargetMetadata {
    label: string
    description: string
    icon: ComponentType<{ className?: string }>
}

export interface SaveAsTarget extends SaveAsTargetMetadata {
    id: SaveAsTargetId
    recommended: boolean
    disabledReason?: string | null
    dataAttr?: string
}

export interface SaveAsChooserProps {
    isOpen: boolean
    targets: SaveAsTarget[]
    onClose: () => void
    onSelect: (target: SaveAsTargetId) => void
}

export const SAVE_AS_TARGETS: Record<SaveAsTargetId, SaveAsTargetMetadata> = {
    insight: {
        label: 'Insight',
        description: 'Visualize and share the query results.',
        icon: IconGraph,
    },
    view: {
        label: 'View',
        description: 'Reuse the query results in other SQL queries.',
        icon: IconDatabase,
    },
    endpoint: {
        label: 'Endpoint',
        description: 'Make the query available through an API.',
        icon: IconEndpoints,
    },
    metric: {
        label: 'Metric',
        description: 'Define a reusable business measure.',
        icon: IconCalculator,
    },
}
