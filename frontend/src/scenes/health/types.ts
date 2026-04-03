export type HealthIssueSeverity = 'critical' | 'warning' | 'info'
export type HealthIssueStatus = 'active' | 'resolved'
export const SEVERITY_ORDER: HealthIssueSeverity[] = ['critical', 'warning', 'info']

export interface HealthIssue {
    id: string
    kind: string
    severity: HealthIssueSeverity
    status: HealthIssueStatus
    dismissed: boolean
    payload: Record<string, any>
    created_at: string
    updated_at: string
    resolved_at: string | null
}

export interface HealthIssueSummary {
    total: number
    by_severity: Partial<Record<HealthIssueSeverity, number>>
    by_kind: Record<string, number>
}

export interface CategoryHealthSummary {
    category: string
    issueCount: number
    worstSeverity: HealthIssueSeverity | null
}
