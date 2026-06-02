export type PulseDigestStatus = 'pending' | 'generating' | 'delivered' | 'failed'
export type PulseSubscriptionFrequency = 'weekly' | 'daily'
export type PulseDetectionMode = 'change_v1' | 'discovery'
export type PulseSensitivity = 'conservative' | 'balanced' | 'sensitive' | 'custom'

export interface PulseDigestSummary {
    id: string
    period_start: string
    period_end: string
    status: PulseDigestStatus
    error: Record<string, any> | null
    created_at: string
    finding_count: number
    summary: string
}

// A same-period change (feature flag, experiment, annotation) the finding's narrative tied to it. The
// frontend builds the link from (type, id) — mirroring how replay session ids become links.
export interface PulseReference {
    type: 'feature_flag' | 'experiment' | 'annotation' | string
    label: string
    id?: string
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
    evidence: { session_ids?: string[]; references?: PulseReference[] } | null
    narrative: string
    chart_thumbnail_url: string
    rank: number
    created_at: string
}

export interface PulseDigestDetail extends PulseDigestSummary {
    workflow_run_id: string
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
