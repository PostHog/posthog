/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

export interface InsightsThresholdBoundsApi {
    /**
     * Alert fires when the value drops below this number.
     * @nullable
     */
    lower?: number | null
    /**
     * Alert fires when the value exceeds this number.
     * @nullable
     */
    upper?: number | null
}

export type InsightThresholdTypeApi = (typeof InsightThresholdTypeApi)[keyof typeof InsightThresholdTypeApi]

export const InsightThresholdTypeApi = {
    Absolute: 'absolute',
    Percentage: 'percentage',
} as const

export interface InsightThresholdApi {
    bounds?: InsightsThresholdBoundsApi | null
    /** Whether bounds are compared as absolute values or as percentage change from the previous interval. */
    type: InsightThresholdTypeApi
}

export interface ThresholdApi {
    readonly id: string
    readonly created_at: string
    /** Optional name for the threshold. */
    name?: string
    /** Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage). */
    configuration: InsightThresholdApi
}

export type AlertConditionTypeApi = (typeof AlertConditionTypeApi)[keyof typeof AlertConditionTypeApi]

export const AlertConditionTypeApi = {
    AbsoluteValue: 'absolute_value',
    RelativeIncrease: 'relative_increase',
    RelativeDecrease: 'relative_decrease',
} as const

export interface AlertConditionApi {
    type: AlertConditionTypeApi
}

/**
 * * `Firing` - Firing
 * `Not firing` - Not firing
 * `Errored` - Errored
 * `Snoozed` - Snoozed
 */
export type AlertCheckStateEnumApi = (typeof AlertCheckStateEnumApi)[keyof typeof AlertCheckStateEnumApi]

export const AlertCheckStateEnumApi = {
    Firing: 'Firing',
    NotFiring: 'Not firing',
    Errored: 'Errored',
    Snoozed: 'Snoozed',
} as const

export interface AlertCheckApi {
    readonly id: string
    readonly created_at: string
    /** @nullable */
    readonly calculated_value: number | null
    readonly state: AlertCheckStateEnumApi
    readonly targets_notified: boolean
    readonly anomaly_scores: unknown | null
    readonly triggered_points: unknown | null
    readonly triggered_dates: unknown | null
    /** @nullable */
    readonly interval: string | null
}

export type TrendsAlertConfigApiType = (typeof TrendsAlertConfigApiType)[keyof typeof TrendsAlertConfigApiType]

export const TrendsAlertConfigApiType = {
    TrendsAlertConfig: 'TrendsAlertConfig',
} as const

export interface TrendsAlertConfigApi {
    /**
     * When true, evaluate the current (still incomplete) time interval in addition to completed ones.
     * @nullable
     */
    check_ongoing_interval?: boolean | null
    /** Zero-based index of the series in the insight's query to monitor. */
    series_index: number
    type?: TrendsAlertConfigApiType
}

export interface PreprocessingConfigApi {
    /**
     * Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)
     * @nullable
     */
    diffs_n?: number | null
    /**
     * Number of lag features. 0 = none, >0 = include n lagged values (default: 0)
     * @nullable
     */
    lags_n?: number | null
    /**
     * Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)
     * @nullable
     */
    smooth_n?: number | null
}

export type ZScoreDetectorConfigApiType = (typeof ZScoreDetectorConfigApiType)[keyof typeof ZScoreDetectorConfigApiType]

export const ZScoreDetectorConfigApiType = {
    Zscore: 'zscore',
} as const

export interface ZScoreDetectorConfigApi {
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /**
     * Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)
     * @nullable
     */
    threshold?: number | null
    type?: ZScoreDetectorConfigApiType
    /**
     * Rolling window size for calculating mean/std (default: 30)
     * @nullable
     */
    window?: number | null
}

export type MADDetectorConfigApiType = (typeof MADDetectorConfigApiType)[keyof typeof MADDetectorConfigApiType]

export const MADDetectorConfigApiType = {
    Mad: 'mad',
} as const

export interface MADDetectorConfigApi {
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /**
     * Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)
     * @nullable
     */
    threshold?: number | null
    type?: MADDetectorConfigApiType
    /**
     * Rolling window size for calculating median/MAD (default: 30)
     * @nullable
     */
    window?: number | null
}

export type ThresholdDetectorConfigApiType =
    (typeof ThresholdDetectorConfigApiType)[keyof typeof ThresholdDetectorConfigApiType]

export const ThresholdDetectorConfigApiType = {
    Threshold: 'threshold',
} as const

export interface ThresholdDetectorConfigApi {
    /**
     * Lower bound - values below this are anomalies
     * @nullable
     */
    lower_bound?: number | null
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    type?: ThresholdDetectorConfigApiType
    /**
     * Upper bound - values above this are anomalies
     * @nullable
     */
    upper_bound?: number | null
}

export type EnsembleOperatorApi = (typeof EnsembleOperatorApi)[keyof typeof EnsembleOperatorApi]

export const EnsembleOperatorApi = {
    And: 'and',
    Or: 'or',
} as const

export type EnsembleDetectorConfigApiType =
    (typeof EnsembleDetectorConfigApiType)[keyof typeof EnsembleDetectorConfigApiType]

export const EnsembleDetectorConfigApiType = {
    Ensemble: 'ensemble',
} as const

export interface EnsembleDetectorConfigApi {
    /** Sub-detector configurations (minimum 2) */
    detectors: (ZScoreDetectorConfigApi | MADDetectorConfigApi | ThresholdDetectorConfigApi)[]
    /** How to combine sub-detector results */
    operator: EnsembleOperatorApi
    type?: EnsembleDetectorConfigApiType
}

/**
 * Detector configuration types
 */
export type DetectorConfigApi =
    | EnsembleDetectorConfigApi
    | ZScoreDetectorConfigApi
    | MADDetectorConfigApi
    | ThresholdDetectorConfigApi

/**
 * * `hourly` - hourly
 * `daily` - daily
 * `weekly` - weekly
 * `monthly` - monthly
 */
export type CalculationIntervalEnumApi = (typeof CalculationIntervalEnumApi)[keyof typeof CalculationIntervalEnumApi]

export const CalculationIntervalEnumApi = {
    Hourly: 'hourly',
    Daily: 'daily',
    Weekly: 'weekly',
    Monthly: 'monthly',
} as const

export interface AlertApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** Insight ID monitored by this alert. Note: Response returns full InsightBasicSerializer object. */
    insight: number
    /** Human-readable name for the alert. */
    name?: string
    /** User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object. */
    subscribed_users: number[]
    /** Threshold configuration with bounds and type for evaluating the alert. */
    threshold: ThresholdApi
    /** Alert condition type. Determines how the value is evaluated: absolute_value, relative_increase, or relative_decrease. */
    condition?: AlertConditionApi | null
    /** Current alert state: Firing, Not firing, Errored, or Snoozed. */
    readonly state: string
    /** Whether the alert is actively being evaluated. */
    enabled?: boolean
    /** @nullable */
    readonly last_notified_at: string | null
    /** @nullable */
    readonly last_checked_at: string | null
    /** @nullable */
    readonly next_check_at: string | null
    /** The last 5 alert check results (only populated on retrieve). */
    readonly checks: readonly AlertCheckApi[]
    /** Trends-specific alert configuration. Includes series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval). */
    config?: TrendsAlertConfigApi | null
    detector_config?: DetectorConfigApi | null
    /** How often the alert is checked: hourly, daily, weekly, or monthly.

* `hourly` - hourly
* `daily` - daily
* `weekly` - weekly
* `monthly` - monthly */
    calculation_interval?: CalculationIntervalEnumApi | NullEnumApi | null
    /**
     * Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze.
     * @nullable
     */
    snoozed_until?: string | null
    /**
     * Skip alert evaluation on weekends (Saturday and Sunday).
     * @nullable
     */
    skip_weekend?: boolean | null
    /**
     * The last calculated value from the most recent alert check.
     * @nullable
     */
    readonly last_value: number | null
}

export interface PaginatedAlertListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AlertApi[]
}

export interface PatchedAlertApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /** Insight ID monitored by this alert. Note: Response returns full InsightBasicSerializer object. */
    insight?: number
    /** Human-readable name for the alert. */
    name?: string
    /** User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object. */
    subscribed_users?: number[]
    /** Threshold configuration with bounds and type for evaluating the alert. */
    threshold?: ThresholdApi
    /** Alert condition type. Determines how the value is evaluated: absolute_value, relative_increase, or relative_decrease. */
    condition?: AlertConditionApi | null
    /** Current alert state: Firing, Not firing, Errored, or Snoozed. */
    readonly state?: string
    /** Whether the alert is actively being evaluated. */
    enabled?: boolean
    /** @nullable */
    readonly last_notified_at?: string | null
    /** @nullable */
    readonly last_checked_at?: string | null
    /** @nullable */
    readonly next_check_at?: string | null
    /** The last 5 alert check results (only populated on retrieve). */
    readonly checks?: readonly AlertCheckApi[]
    /** Trends-specific alert configuration. Includes series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval). */
    config?: TrendsAlertConfigApi | null
    detector_config?: DetectorConfigApi | null
    /** How often the alert is checked: hourly, daily, weekly, or monthly.

* `hourly` - hourly
* `daily` - daily
* `weekly` - weekly
* `monthly` - monthly */
    calculation_interval?: CalculationIntervalEnumApi | NullEnumApi | null
    /**
     * Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze.
     * @nullable
     */
    snoozed_until?: string | null
    /**
     * Skip alert evaluation on weekends (Saturday and Sunday).
     * @nullable
     */
    skip_weekend?: boolean | null
    /**
     * The last calculated value from the most recent alert check.
     * @nullable
     */
    readonly last_value?: number | null
}

export type AlertsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
