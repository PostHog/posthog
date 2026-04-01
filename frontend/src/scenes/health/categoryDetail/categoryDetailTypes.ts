import type { ComponentType } from 'react'

import type { HealthIssue, HealthIssueSeverity } from '../types'

export interface CategoryDetailContentProps {
    issues: HealthIssue[]
    statusSummary: { count: number; worstSeverity: HealthIssueSeverity | null; isHealthy: boolean }
    isLoading: boolean
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
    onRefresh: () => void
    showDismissed: boolean
    onSetShowDismissed: (show: boolean) => void
}

export type CategoryDetailContentComponent = ComponentType<CategoryDetailContentProps>

export interface HealthTableProps {
    issues: HealthIssue[]
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}

export type HealthTableComponent = ComponentType<HealthTableProps>
