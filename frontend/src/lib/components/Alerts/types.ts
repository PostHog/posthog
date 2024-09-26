import {
    AlertCalculationInterval,
    AlertCondition,
    AlertState,
    InsightThreshold,
    TrendsAlertConfig,
} from '~/queries/schema'
import { QueryBasedInsightModel, UserBasicType } from '~/types'

export type AlertConfig = TrendsAlertConfig

export interface AlertTypeBase {
    name: string
    condition: AlertCondition
    enabled: boolean
    insight: QueryBasedInsightModel
    config: AlertConfig
}

export interface AlertTypeWrite extends AlertTypeBase {
    subscribed_users: number[]
}

export interface AlertCheck {
    id: string
    created_at: string
    calculated_value: number
    state: AlertState
    targets_notified: boolean
}

export interface AlertType extends AlertTypeBase {
    id: string
    subscribed_users: UserBasicType[]
    threshold: { configuration: InsightThreshold }
    created_by: UserBasicType
    created_at: string
    state: AlertState
    last_notified_at: string
    last_checked_at: string
    checks: AlertCheck[]
    calculation_interval: AlertCalculationInterval
}
