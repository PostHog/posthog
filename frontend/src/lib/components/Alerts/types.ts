import {
    AlertCalculationInterval,
    AlertCondition,
    AlertScheduleRestriction,
    AlertScheduleRestrictionWindow,
    AlertState,
    DetectorConfig,
    InsightThreshold,
    TrendsAlertConfig,
} from '~/queries/schema/schema-general'
import { QueryBasedInsightModel, UserBasicType } from '~/types'

export type AlertConfig = TrendsAlertConfig

export type BlockedWindow = AlertScheduleRestrictionWindow

/** Quiet hours / blocked local periods; times are HH:MM in the project timezone. */
export type ScheduleRestriction = AlertScheduleRestriction

export interface SubDetectorScores {
    type: string
    scores: (number | null)[]
}

export interface BreakdownSimulationResult {
    label: string
    data: number[]
    dates: string[]
    scores: (number | null)[]
    triggered_indices: number[]
    triggered_dates: string[]
    total_points: number
    anomaly_count: number
    sub_detector_scores?: SubDetectorScores[]
}

export interface AlertSimulationResult {
    data: number[]
    dates: string[]
    scores: (number | null)[]
    triggered_indices: number[]
    triggered_dates: string[]
    interval: string | null
    total_points: number
    anomaly_count: number
    sub_detector_scores?: SubDetectorScores[]
    breakdown_results?: BreakdownSimulationResult[]
}

export interface AnomalyPoint {
    index: number
    date: string
    score: number | null
    seriesIndex: number
}

export type InvestigationInconclusiveAction = 'notify' | 'suppress'

export interface AlertTypeBase {
    name: string
    condition: AlertCondition
    threshold: { configuration: InsightThreshold }
    enabled: boolean
    insight: QueryBasedInsightModel
    config: AlertConfig
    skip_weekend?: boolean
    schedule_restriction?: ScheduleRestriction | null
    detector_config?: DetectorConfig | null
    investigation_agent_enabled?: boolean
    investigation_gates_notifications?: boolean
    investigation_inconclusive_action?: InvestigationInconclusiveAction
}

export interface AlertTypeWrite extends Omit<AlertTypeBase, 'insight'> {
    subscribed_users: number[]
    insight: number
    snoozed_until?: string | null
    detector_config?: DetectorConfig | null
}

export type InvestigationStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped'
export type InvestigationVerdict = 'true_positive' | 'false_positive' | 'inconclusive'

export interface AlertCheck {
    id: string
    created_at: string
    calculated_value: number
    state: AlertState
    targets_notified: boolean
    anomaly_scores?: (number | null)[] | null
    triggered_points?: number[] | null
    triggered_dates?: string[] | null
    interval?: string | null
    triggered_metadata?: Record<string, unknown> | null
    investigation_status?: InvestigationStatus | null
    investigation_verdict?: InvestigationVerdict | null
    investigation_summary?: string | null
    investigation_notebook_short_id?: string | null
    notification_sent_at?: string | null
    notification_suppressed_by_agent?: boolean
}

export interface AlertType extends AlertTypeBase {
    id: string
    subscribed_users: UserBasicType[]
    condition: AlertCondition
    created_by: UserBasicType
    created_at: string
    state: AlertState
    last_notified_at: string
    last_checked_at: string
    next_check_at?: string | null
    checks_total?: number
    checks: AlertCheck[]
    calculation_interval: AlertCalculationInterval
    snoozed_until?: string
    last_value?: number
}
