export type HealthIssueSeverity = 'critical' | 'warning' | 'info'
export type HealthIssueStatus = 'active' | 'resolved'
export const SEVERITY_ORDER: HealthIssueSeverity[] = ['critical', 'warning', 'info']

export const SNOOZE_DURATIONS = [
    { label: 'Snooze for 7 days', duration: '7d' },
    { label: 'Snooze for 30 days', duration: '30d' },
    { label: 'Snooze for 90 days', duration: '90d' },
]

export const REFRESH_COOLDOWN_MS = 5 * 60 * 1000
export const REFRESH_POLL_INTERVAL_MS = 5000
export const REFRESH_POLL_COUNT = 12

export interface HealthIssue {
    id: string
    kind: string
    severity: HealthIssueSeverity
    status: HealthIssueStatus
    dismissed: boolean
    snoozed_until: string | null
    payload: Record<string, any>
    created_at: string
    updated_at: string
    resolved_at: string | null
}

// A scoped re-check runs one cheap detection, so it gets a shorter cooldown than the
// whole-project refresh. Mirrors HealthIssueKindRefreshThrottle on the backend.
export const KIND_REFRESH_COOLDOWN_MS = 60 * 1000

export type HealthCheckRunStatus = 'never_run' | 'healthy' | 'issues'

export interface HealthCheckState {
    kind: string
    status: HealthCheckRunStatus
    last_run_at: string | null
    next_run_at: string | null
    schedule: string | null
    stale: boolean
}

export interface HealthChecksResponse {
    results: HealthCheckState[]
}

export interface HealthIssueCounts {
    total: number
    by_severity: Partial<Record<HealthIssueSeverity, number>>
    by_kind: Record<string, number>
}

export interface HealthIssueSummary {
    unsnoozed: HealthIssueCounts
    snoozed: HealthIssueCounts
}

export interface CategoryHealthSummary {
    category: string
    issueCount: number
    worstSeverity: HealthIssueSeverity | null
}
