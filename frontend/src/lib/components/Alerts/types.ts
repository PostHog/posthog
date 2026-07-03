import {
    AlertCalculationInterval,
    AlertCondition,
    AlertScheduleRestriction,
    AlertScheduleRestrictionWindow,
    AlertState,
    DetectorConfig,
    ForecastConfig,
    FunnelsAlertConfig,
    HogQLAlertConfig,
    InsightThreshold,
    TrendsAlertConfig,
} from '~/queries/schema/schema-general'
import { QueryBasedInsightModel, UserBasicType } from '~/types'

export type AlertConfig = TrendsAlertConfig | HogQLAlertConfig | FunnelsAlertConfig

export const isTrendsAlertConfig = (config: AlertConfig | null | undefined): config is TrendsAlertConfig =>
    config?.type === 'TrendsAlertConfig'

export const isHogQLAlertConfig = (config: AlertConfig | null | undefined): config is HogQLAlertConfig =>
    config?.type === 'HogQLAlertConfig'

export const isFunnelsAlertConfig = (config: AlertConfig | null | undefined): config is FunnelsAlertConfig =>
    config?.type === 'FunnelsAlertConfig'

/** SQL alert in any-row mode: every result row is checked (one entity per row), which changes
 * row labeling and history rendering versus the single-value modes. */
export const isAnyRowHogQLConfig = (config: AlertConfig | null | undefined): boolean =>
    isHogQLAlertConfig(config) && config.evaluation === 'any_row'

// Capability helpers — read at call sites instead of bare `isTrendsAlertConfig`/`isHogQLAlertConfig`
// checks, so the intent ("does this alert kind support X") is explicit. Kept separate even where
// they coincide today (all trends-only) because the capabilities are independent and may diverge.

/** Trends alerts and historical-trend funnels evaluate a time-bucketed series, so they can check the
 * current (incomplete) interval. SQL alerts evaluate whatever the query returns — no partial interval.
 * Type guard so call sites can read `check_ongoing_interval` after the check. This is config-level: a
 * steps funnel also matches (it carries the field), so the UI additionally gates the funnel case on
 * whether it's a trends funnel — only those are a time series. */
export const supportsOngoingInterval = (
    config: AlertConfig | null | undefined
): config is TrendsAlertConfig | FunnelsAlertConfig => isTrendsAlertConfig(config) || isFunnelsAlertConfig(config)

/** Trends and funnel alerts evaluate over the insight's time window/interval; SQL alerts own their
 * own window inside the query, so there's no interval to echo in the UI. */
export const supportsTimeWindow = (config: AlertConfig | null | undefined): boolean => !isHogQLAlertConfig(config)

/** Anomaly detection needs a time series to score: trends, or SQL in last/first-row mode (an
 * any-row SQL alert's rows are unrelated entities, not a time axis, so there's nothing to score). */
export const supportsAnomalyDetection = (config: AlertConfig | null | undefined): boolean =>
    isTrendsAlertConfig(config) || (isHogQLAlertConfig(config) && !isAnyRowHogQLConfig(config))

/** Forecasting needs a plain time series with enough history: trends only in v1 (no SQL, no funnels). */
export const supportsForecast = (config: AlertConfig | null | undefined): boolean => isTrendsAlertConfig(config)

/** Which evaluation strategy the alert editor is configuring. */
export type AlertMode = 'detector' | 'threshold' | 'forecast'

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
    forecast_config?: ForecastConfig | null
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
    calculated_value: number | null
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
