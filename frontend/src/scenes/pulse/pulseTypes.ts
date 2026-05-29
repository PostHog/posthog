export type PulseDigestStatus = 'pending' | 'generating' | 'delivered' | 'failed'
export type PulseFindingFeedbackAction = 'pending' | 'up' | 'down' | 'dismissed' | 'snoozed'
export type PulseSubscriptionFrequency = 'weekly' | 'daily'
export type PulseDetectionMode = 'change_v1' | 'discovery'
export type PulseSensitivity = 'conservative' | 'balanced' | 'sensitive' | 'custom'

export interface PulseDigestSummary {
    id: string
    period_start: string
    period_end: string
    status: PulseDigestStatus
    created_at: string
    finding_count: number
}

export interface PulseFindingType {
    id: string
    digest: string
    metric_label: string
    metric_descriptor: Record<string, any>
    current_value: number
    baseline_value: number
    change_pct: number
    robust_z: number
    impact: number
    attribution_breakdown: Record<string, any> | null
    narrative: string
    chart_thumbnail_url: string
    feedback: PulseFindingFeedbackAction
    snoozed_until: string | null
    rank: number
    created_at: string
}

export interface PulseDigestDetail extends PulseDigestSummary {
    workflow_run_id: string
    error: Record<string, any> | null
    findings: PulseFindingType[]
}

export interface PulseSubscriptionType {
    id: string | null
    enabled: boolean
    frequency: PulseSubscriptionFrequency
    detection_mode: PulseDetectionMode
    sensitivity: PulseSensitivity
    min_change_pct: number
    baseline_weeks: number
    max_findings: number
    robust_z_threshold: number
    last_scan_at: string | null
    next_scan_at: string | null
    created_at: string | null
}

export interface PulseWatchedCandidate {
    source: string
    source_id: string | null
    label: string
    query: Record<string, any>
}
