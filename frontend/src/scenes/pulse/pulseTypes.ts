export const PULSE_ACTIVITY_SCOPE = 'Pulse'

export type PulseDigestStatus = 'pending' | 'generating' | 'delivered' | 'failed'
export type PulseFindingFeedbackAction = 'pending' | 'up' | 'down' | 'dismissed' | 'snoozed'
export type PulseSubscriptionFrequency = 'weekly' | 'daily'
export type PulseChannel = 'in_app' | 'slack' | 'email'

export interface PulseDigestSummary {
    id: string
    period_start: string
    period_end: string
    status: PulseDigestStatus
    delivered_to: Record<string, any>
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
    z_score: number
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
    enabled_channels: PulseChannel[]
    slack_channel_id: string
    email_recipients: string[]
    last_scan_at: string | null
    next_scan_at: string | null
    created_at: string | null
}
