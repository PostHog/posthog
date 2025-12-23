import {
    AlertCalculationInterval,
    AlertCondition,
    AlertState,
    DetectorConfig,
    InsightThreshold,
    TrendsAlertConfig,
} from '~/queries/schema/schema-general'
import { QueryBasedInsightModel, UserBasicType } from '~/types'

export type AlertConfig = TrendsAlertConfig

export interface AlertTypeBase {
    name: string
    condition: AlertCondition
    threshold: { configuration: InsightThreshold }
    enabled: boolean
    insight: QueryBasedInsightModel
    config: AlertConfig
    skip_weekend?: boolean
    detector_config?: DetectorConfig | null
}

export interface AlertTypeWrite extends Omit<AlertTypeBase, 'insight'> {
    subscribed_users: number[]
    insight: number
    snoozed_until?: string | null
}

export interface AlertCheck {
    id: string
    created_at: string
    calculated_value: number
    state: AlertState
    targets_notified: boolean
    anomaly_scores?: (number | null)[] | null
    triggered_points?: number[] | null
    triggered_dates?: string[] | null // Dates of anomaly points for chart matching
    interval?: string | null // Insight interval when check was created
}

export interface BackfillResult {
    triggered_indices: number[]
    scores: (number | null)[]
    total_points: number
    anomaly_count: number
    data?: number[]
    labels?: string[]
    dates?: string[]
    series_label?: string
    saved_check_id?: string
    check_state?: string
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
    checks: AlertCheck[]
    calculation_interval: AlertCalculationInterval
    snoozed_until?: string
}
