import {
    AlertCalculationInterval,
    AlertCondition,
    AlertState,
    ForecastAlertConfig,
    InsightThreshold,
    TrendsAlertConfig,
} from '~/queries/schema/schema-general'
import { QueryBasedInsightModel, UserBasicType } from '~/types'

export type AlertConfig = TrendsAlertConfig | ForecastAlertConfig

export interface AlertTypeBase {
    name: string
    condition: AlertCondition
    threshold: { configuration: InsightThreshold }
    enabled: boolean
    insight: QueryBasedInsightModel
    config: AlertConfig
    skip_weekend?: boolean
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
    is_backfill: boolean
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

export interface ForecastResult {
    id: string
    alert_configuration: string
    series_index: number
    breakdown_value: string | null
    forecast_timestamp: string
    predicted_value: number
    lower_bound: number
    upper_bound: number
    confidence_level: number
    computed_at: string
    model_version: string
}
