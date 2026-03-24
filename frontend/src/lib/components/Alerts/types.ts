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

export interface SubDetectorScores {
    type: string
    scores: (number | null)[]
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
}

export interface AnomalyPoint {
    index: number
    date: string
    score: number | null
    seriesIndex: number
}

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
    detector_config?: DetectorConfig | null
}

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
    last_value?: number
}
