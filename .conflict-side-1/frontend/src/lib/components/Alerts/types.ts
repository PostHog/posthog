import {
    AlertCalculationInterval,
    AlertCondition,
    AlertState,
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
