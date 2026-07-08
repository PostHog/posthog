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
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
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

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface InsightsThresholdBoundsApi {
    /** Alert fires when the value drops below this number. */
    lower?: number | null
    /** Alert fires when the value exceeds this number. */
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
    /**
     * Optional name for the threshold.
     * @maxLength 255
     */
    name?: string
    /** Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage). For threshold-based alerts (no detector_config), at least one of lower or upper must be set. */
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
 * * `Not firing` - Not firing
 * * `Errored` - Errored
 * * `Snoozed` - Snoozed
 */
export type AlertCheckStateEnumApi = (typeof AlertCheckStateEnumApi)[keyof typeof AlertCheckStateEnumApi]

export const AlertCheckStateEnumApi = {
    Firing: 'Firing',
    NotFiring: 'Not firing',
    Errored: 'Errored',
    Snoozed: 'Snoozed',
} as const

/**
 * * `pending` - pending
 * * `running` - running
 * * `done` - done
 * * `failed` - failed
 * * `skipped` - skipped
 */
export type InvestigationStatusEnumApi = (typeof InvestigationStatusEnumApi)[keyof typeof InvestigationStatusEnumApi]

export const InvestigationStatusEnumApi = {
    Pending: 'pending',
    Running: 'running',
    Done: 'done',
    Failed: 'failed',
    Skipped: 'skipped',
} as const

/**
 * * `true_positive` - true_positive
 * * `false_positive` - false_positive
 * * `inconclusive` - inconclusive
 */
export type InvestigationVerdictEnumApi = (typeof InvestigationVerdictEnumApi)[keyof typeof InvestigationVerdictEnumApi]

export const InvestigationVerdictEnumApi = {
    TruePositive: 'true_positive',
    FalsePositive: 'false_positive',
    Inconclusive: 'inconclusive',
} as const

export interface AlertCheckApi {
    readonly id: string
    readonly created_at: string
    /** @nullable */
    readonly calculated_value: number | null
    readonly state: AlertCheckStateEnumApi
    readonly targets_notified: boolean
    readonly anomaly_scores: unknown
    readonly triggered_points: unknown
    readonly triggered_dates: unknown
    /** @nullable */
    readonly interval: string | null
    readonly triggered_metadata: unknown
    readonly investigation_status: InvestigationStatusEnumApi | null
    readonly investigation_verdict: InvestigationVerdictEnumApi | null
    /** @nullable */
    readonly investigation_summary: string | null
    /**
     * Short ID of the Notebook produced by the investigation agent, when the agent ran for this check.
     * @nullable
     */
    readonly investigation_notebook_short_id: string | null
    /** @nullable */
    readonly notification_sent_at: string | null
    readonly notification_suppressed_by_agent: boolean
}

export type TrendsAlertConfigApiType = (typeof TrendsAlertConfigApiType)[keyof typeof TrendsAlertConfigApiType]

export const TrendsAlertConfigApiType = {
    TrendsAlertConfig: 'TrendsAlertConfig',
} as const

export interface TrendsAlertConfigApi {
    /** When true, evaluate the current (still incomplete) time interval in addition to completed ones. */
    check_ongoing_interval?: boolean | null
    /** Zero-based index of the series in the insight's query to monitor. */
    series_index: number
    type: TrendsAlertConfigApiType
}

export type HogQLAlertEvaluationApi = (typeof HogQLAlertEvaluationApi)[keyof typeof HogQLAlertEvaluationApi]

export const HogQLAlertEvaluationApi = {
    LastRow: 'last_row',
    FirstRow: 'first_row',
    AnyRow: 'any_row',
} as const

export type HogQLAlertConfigApiType = (typeof HogQLAlertConfigApiType)[keyof typeof HogQLAlertConfigApiType]

export const HogQLAlertConfigApiType = {
    HogQLAlertConfig: 'HogQLAlertConfig',
} as const

export interface HogQLAlertConfigApi {
    /** Name of the result column to evaluate. When unset, the single numeric column is used (an error if the result has more than one numeric column). */
    column?: string | null
    /** How to read the result rows — an explicit choice, no implicit default. */
    evaluation: HogQLAlertEvaluationApi
    /** Column whose value labels the evaluated row(s) in breach messages: every row in `any_row` mode, or the single evaluated row in `last_row`/`first_row`. When unset, the first non-evaluated column is used, falling back to the row number (any_row) or the value column name (last_row/first_row). */
    label_column?: string | null
    type: HogQLAlertConfigApiType
}

export type FunnelConversionMetricApi = (typeof FunnelConversionMetricApi)[keyof typeof FunnelConversionMetricApi]

export const FunnelConversionMetricApi = {
    ConversionFromStart: 'conversion_from_start',
    ConversionFromPrevious: 'conversion_from_previous',
} as const

export type FunnelsAlertConfigApiType = (typeof FunnelsAlertConfigApiType)[keyof typeof FunnelsAlertConfigApiType]

export const FunnelsAlertConfigApiType = {
    FunnelsAlertConfig: 'FunnelsAlertConfig',
} as const

export interface FunnelsAlertConfigApi {
    /** When true, evaluate the current (still in-progress) period; by default only completed periods are used. */
    check_ongoing_interval?: boolean | null
    /** Zero-based step index to evaluate. Null = the last step (overall conversion). */
    funnel_step?: number | null
    metric: FunnelConversionMetricApi
    type: FunnelsAlertConfigApiType
}

/**
 * Per-insight-kind alert config, discriminated by ``type`` — keeps the OpenAPI (and the
 * generated frontend types and MCP tool schemas) in sync with every kind alerts support.
 */
export type AlertConfigUnionApi = TrendsAlertConfigApi | HogQLAlertConfigApi | FunnelsAlertConfigApi

export interface PreprocessingConfigApi {
    /** Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0) */
    diffs_n?: number | null
    /** Number of lag features. 0 = none, >0 = include n lagged values (default: 0) */
    lags_n?: number | null
    /** Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0) */
    smooth_n?: number | null
}

export interface ZScoreDetectorConfigApi {
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9) */
    threshold?: number | null
    type?: 'zscore'
    /** Rolling window size for calculating mean/std (default: 30) */
    window?: number | null
}

export interface MADDetectorConfigApi {
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9) */
    threshold?: number | null
    type?: 'mad'
    /** Rolling window size for calculating median/MAD (default: 30) */
    window?: number | null
}

export interface IQRDetectorConfigApi {
    /** IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers) */
    multiplier?: number | null
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    type?: 'iqr'
    /** Rolling window size for calculating quartiles (default: 30) */
    window?: number | null
}

export interface ThresholdDetectorConfigApi {
    /** Lower bound - values below this are anomalies */
    lower_bound?: number | null
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    type?: 'threshold'
    /** Upper bound - values above this are anomalies */
    upper_bound?: number | null
}

export interface ECODDetectorConfigApi {
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold (default: 0.9) */
    threshold?: number | null
    type?: 'ecod'
    /** Rolling window size — how many historical data points to train on (default: based on calculation interval) */
    window?: number | null
}

export interface COPODDetectorConfigApi {
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold (default: 0.9) */
    threshold?: number | null
    type?: 'copod'
    /** Rolling window size — how many historical data points to train on (default: based on calculation interval) */
    window?: number | null
}

export interface IsolationForestDetectorConfigApi {
    /** Number of trees in the forest (default: 100) */
    n_estimators?: number | null
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold (default: 0.9) */
    threshold?: number | null
    type?: 'isolation_forest'
    /** Rolling window size — how many historical data points to train on (default: based on calculation interval) */
    window?: number | null
}

export type MethodApi = (typeof MethodApi)[keyof typeof MethodApi]

export const MethodApi = {
    Largest: 'largest',
    Mean: 'mean',
    Median: 'median',
} as const

export interface KNNDetectorConfigApi {
    /** Distance method: 'largest', 'mean', 'median' (default: 'largest') */
    method?: MethodApi | null
    /** Number of neighbors to consider (default: 5) */
    n_neighbors?: number | null
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold (default: 0.9) */
    threshold?: number | null
    type?: 'knn'
    /** Rolling window size — how many historical data points to train on (default: based on calculation interval) */
    window?: number | null
}

export interface HBOSDetectorConfigApi {
    /** Number of histogram bins (default: 10) */
    n_bins?: number | null
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold (default: 0.9) */
    threshold?: number | null
    type?: 'hbos'
    /** Rolling window size — how many historical data points to train on (default: based on calculation interval) */
    window?: number | null
}

export interface LOFDetectorConfigApi {
    /** Number of neighbors for LOF (default: 20) */
    n_neighbors?: number | null
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold (default: 0.9) */
    threshold?: number | null
    type?: 'lof'
    /** Rolling window size — how many historical data points to train on (default: based on calculation interval) */
    window?: number | null
}

export interface OCSVMDetectorConfigApi {
    /** SVM kernel type (default: "rbf") */
    kernel?: string | null
    /** Upper bound on training errors fraction (default: 0.1) */
    nu?: number | null
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold (default: 0.9) */
    threshold?: number | null
    type?: 'ocsvm'
    /** Rolling window size — how many historical data points to train on (default: based on calculation interval) */
    window?: number | null
}

export interface PCADetectorConfigApi {
    /** Preprocessing transforms applied before detection */
    preprocessing?: PreprocessingConfigApi | null
    /** Anomaly probability threshold (default: 0.9) */
    threshold?: number | null
    type?: 'pca'
    /** Rolling window size — how many historical data points to train on (default: based on calculation interval) */
    window?: number | null
}

export type EnsembleOperatorApi = (typeof EnsembleOperatorApi)[keyof typeof EnsembleOperatorApi]

export const EnsembleOperatorApi = {
    And: 'and',
    Or: 'or',
} as const

export interface EnsembleDetectorConfigApi {
    /** Sub-detector configurations (minimum 2) */
    detectors: (
        | ZScoreDetectorConfigApi
        | MADDetectorConfigApi
        | IQRDetectorConfigApi
        | ThresholdDetectorConfigApi
        | ECODDetectorConfigApi
        | COPODDetectorConfigApi
        | IsolationForestDetectorConfigApi
        | KNNDetectorConfigApi
        | HBOSDetectorConfigApi
        | LOFDetectorConfigApi
        | OCSVMDetectorConfigApi
        | PCADetectorConfigApi
    )[]
    /** How to combine sub-detector results */
    operator: EnsembleOperatorApi
    type?: 'ensemble'
}

/**
 * Detector configuration types
 */
export type DetectorConfigApi =
    | EnsembleDetectorConfigApi
    | ZScoreDetectorConfigApi
    | MADDetectorConfigApi
    | IQRDetectorConfigApi
    | ThresholdDetectorConfigApi
    | ECODDetectorConfigApi
    | COPODDetectorConfigApi
    | IsolationForestDetectorConfigApi
    | KNNDetectorConfigApi
    | HBOSDetectorConfigApi
    | LOFDetectorConfigApi
    | OCSVMDetectorConfigApi
    | PCADetectorConfigApi

/**
 * * `real_time` - real_time
 * * `every_15_minutes` - every_15_minutes
 * * `hourly` - hourly
 * * `daily` - daily
 * * `weekly` - weekly
 * * `monthly` - monthly
 */
export type CalculationIntervalEnumApi = (typeof CalculationIntervalEnumApi)[keyof typeof CalculationIntervalEnumApi]

export const CalculationIntervalEnumApi = {
    RealTime: 'real_time',
    Every15Minutes: 'every_15_minutes',
    Hourly: 'hourly',
    Daily: 'daily',
    Weekly: 'weekly',
    Monthly: 'monthly',
} as const

export interface AlertScheduleRestrictionWindowApi {
    /** Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)). */
    start: string
    /** End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally. */
    end: string
}

export interface AlertScheduleRestrictionApi {
    /** Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours. */
    blocked_windows: AlertScheduleRestrictionWindowApi[]
}

/**
 * * `notify` - Notify
 * * `suppress` - Suppress
 */
export type InvestigationInconclusiveActionEnumApi =
    (typeof InvestigationInconclusiveActionEnumApi)[keyof typeof InvestigationInconclusiveActionEnumApi]

export const InvestigationInconclusiveActionEnumApi = {
    Notify: 'notify',
    Suppress: 'suppress',
} as const

export type SearchMatchTypeEnumApi = (typeof SearchMatchTypeEnumApi)[keyof typeof SearchMatchTypeEnumApi]

export const SearchMatchTypeEnumApi = {
    Exact: 'exact',
    Similar: 'similar',
} as const

export interface AlertApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** Insight ID monitored by this alert. Note: Response returns full InsightBasicSerializer object. */
    insight: number
    /**
     * Human-readable name for the alert.
     * @maxLength 255
     */
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
    /** Alert check results. By default returns the last 5. Use checks_date_from and checks_date_to (e.g. '-24h', '-7d') to get checks within a time window, checks_limit to cap how many are returned (default 5, max 500), and checks_offset to skip the newest N checks for pagination (0-based). Newest checks first. Only populated on retrieve. */
    readonly checks: readonly AlertCheckApi[]
    /**
     * Total alert checks matching the retrieve filters (date window). Only set on alert retrieve; omitted otherwise.
     * @nullable
     */
    readonly checks_total: number | null
    /** Per-insight-kind alert configuration, discriminated by `type`. TrendsAlertConfig: series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval). HogQLAlertConfig (SQL insights): column (which result column to evaluate, defaults to the single numeric column), evaluation ('last_row' checks the latest value of an oldest->newest query, 'first_row' checks the first value of a newest->oldest query, 'any_row' fires if any row breaches), and label_column (names the evaluated row(s) in breach messages, in every evaluation mode). FunnelsAlertConfig (funnel insights): funnel_step (the step to monitor, null for the overall last step), metric ('conversion_from_start' or 'conversion_from_previous'), and check_ongoing_interval (historical-trend funnels: also evaluate the current in-progress period). Steps funnels support only absolute_value conditions; historical-trend funnels also support relative_increase/relative_decrease (compared against the prior period). */
    config?: AlertConfigUnionApi | null
    detector_config?: DetectorConfigApi | null
    /** How often the alert is checked: real time (Scale+), every 15 minutes (Boost+), hourly, daily, weekly, or monthly.
     *
     * * `real_time` - real_time
     * * `every_15_minutes` - every_15_minutes
     * * `hourly` - hourly
     * * `daily` - daily
     * * `weekly` - weekly
     * * `monthly` - monthly */
    calculation_interval?: CalculationIntervalEnumApi
    /**
     * Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze.
     * @nullable
     */
    snoozed_until?: string | null
    /**
     * Skip alert evaluation on weekends (Saturday and Sunday, local to project timezone).
     * @nullable
     */
    skip_weekend?: boolean | null
    /** Blocked local time windows (HH:MM in the project timezone). Interval is half-open [start, end): start inclusive, end exclusive. Use blocked_windows array of {start, end}. Null disables. */
    schedule_restriction?: AlertScheduleRestrictionApi | null
    /**
     * The last calculated value from the most recent alert check.
     * @nullable
     */
    readonly last_value: number | null
    /** When enabled, an investigation agent runs on the state transition to firing and writes findings to a Notebook linked from the alert check. Only effective for detector-based (anomaly) alerts. */
    investigation_agent_enabled?: boolean
    /** When enabled (and investigation_agent_enabled is on), notification dispatch is held until the investigation agent produces a verdict. Notifications are suppressed when the verdict is false_positive (and optionally when inconclusive). A safety-net task force-fires after a few minutes if the investigation stalls. */
    investigation_gates_notifications?: boolean
    /** How to handle an 'inconclusive' verdict when notifications are gated. 'notify' is the safe default — an agent that can't be sure is itself useful signal.
     *
     * * `notify` - Notify
     * * `suppress` - Suppress */
    investigation_inconclusive_action?: InvestigationInconclusiveActionEnumApi
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`. */
    readonly search_match_type: SearchMatchTypeEnumApi | null
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
    /**
     * Human-readable name for the alert.
     * @maxLength 255
     */
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
    /** Alert check results. By default returns the last 5. Use checks_date_from and checks_date_to (e.g. '-24h', '-7d') to get checks within a time window, checks_limit to cap how many are returned (default 5, max 500), and checks_offset to skip the newest N checks for pagination (0-based). Newest checks first. Only populated on retrieve. */
    readonly checks?: readonly AlertCheckApi[]
    /**
     * Total alert checks matching the retrieve filters (date window). Only set on alert retrieve; omitted otherwise.
     * @nullable
     */
    readonly checks_total?: number | null
    /** Per-insight-kind alert configuration, discriminated by `type`. TrendsAlertConfig: series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval). HogQLAlertConfig (SQL insights): column (which result column to evaluate, defaults to the single numeric column), evaluation ('last_row' checks the latest value of an oldest->newest query, 'first_row' checks the first value of a newest->oldest query, 'any_row' fires if any row breaches), and label_column (names the evaluated row(s) in breach messages, in every evaluation mode). FunnelsAlertConfig (funnel insights): funnel_step (the step to monitor, null for the overall last step), metric ('conversion_from_start' or 'conversion_from_previous'), and check_ongoing_interval (historical-trend funnels: also evaluate the current in-progress period). Steps funnels support only absolute_value conditions; historical-trend funnels also support relative_increase/relative_decrease (compared against the prior period). */
    config?: AlertConfigUnionApi | null
    detector_config?: DetectorConfigApi | null
    /** How often the alert is checked: real time (Scale+), every 15 minutes (Boost+), hourly, daily, weekly, or monthly.
     *
     * * `real_time` - real_time
     * * `every_15_minutes` - every_15_minutes
     * * `hourly` - hourly
     * * `daily` - daily
     * * `weekly` - weekly
     * * `monthly` - monthly */
    calculation_interval?: CalculationIntervalEnumApi
    /**
     * Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze.
     * @nullable
     */
    snoozed_until?: string | null
    /**
     * Skip alert evaluation on weekends (Saturday and Sunday, local to project timezone).
     * @nullable
     */
    skip_weekend?: boolean | null
    /** Blocked local time windows (HH:MM in the project timezone). Interval is half-open [start, end): start inclusive, end exclusive. Use blocked_windows array of {start, end}. Null disables. */
    schedule_restriction?: AlertScheduleRestrictionApi | null
    /**
     * The last calculated value from the most recent alert check.
     * @nullable
     */
    readonly last_value?: number | null
    /** When enabled, an investigation agent runs on the state transition to firing and writes findings to a Notebook linked from the alert check. Only effective for detector-based (anomaly) alerts. */
    investigation_agent_enabled?: boolean
    /** When enabled (and investigation_agent_enabled is on), notification dispatch is held until the investigation agent produces a verdict. Notifications are suppressed when the verdict is false_positive (and optionally when inconclusive). A safety-net task force-fires after a few minutes if the investigation stalls. */
    investigation_gates_notifications?: boolean
    /** How to handle an 'inconclusive' verdict when notifications are gated. 'notify' is the safe default — an agent that can't be sure is itself useful signal.
     *
     * * `notify` - Notify
     * * `suppress` - Suppress */
    investigation_inconclusive_action?: InvestigationInconclusiveActionEnumApi
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`. */
    readonly search_match_type?: SearchMatchTypeEnumApi | null
}

export interface AlertSimulateApi {
    /** Insight ID to simulate the detector on. */
    insight: number
    /** Detector configuration to simulate. */
    detector_config: DetectorConfigApi
    /** Zero-based index of the series to analyze (trends insights only). */
    series_index?: number
    /**
     * Relative date string for how far back to simulate (e.g. '-24h', '-30d', '-4w'). If not provided, uses the detector's minimum required samples. Trends insights only — a SQL query's own rows are the series.
     * @nullable
     */
    date_from?: string | null
    /** Per-insight-kind alert config. For SQL insights, selects the evaluated column and read direction (last_row/first_row) so the preview matches the alert; ignored for trends. */
    config?: AlertConfigUnionApi | null
}

export type AlertSimulateResponseApiSubDetectorScoresItem = { [key: string]: unknown }

export type BreakdownSimulationResultApiSubDetectorScoresItem = { [key: string]: unknown }

export interface BreakdownSimulationResultApi {
    /** Breakdown value label. */
    label: string
    /** Data values for each point. */
    data: number[]
    /** Date labels for each point. */
    dates: string[]
    /** Anomaly score for each point. */
    scores: (number | null)[]
    /** Indices of points flagged as anomalies. */
    triggered_indices: number[]
    /** Dates of points flagged as anomalies. */
    triggered_dates: string[]
    /** Total number of data points analyzed. */
    total_points: number
    /** Number of anomalies detected. */
    anomaly_count: number
    /** Per-sub-detector scores for ensemble detectors. */
    sub_detector_scores?: BreakdownSimulationResultApiSubDetectorScoresItem[]
}

export interface AlertSimulateResponseApi {
    /** Data values for each point. */
    data: number[]
    /** Date labels for each point. */
    dates: string[]
    /** Anomaly score for each point (null if insufficient data). */
    scores: (number | null)[]
    /** Indices of points flagged as anomalies. */
    triggered_indices: number[]
    /** Dates of points flagged as anomalies. */
    triggered_dates: string[]
    /**
     * Interval of the trends query (hour, day, week, month).
     * @nullable
     */
    interval: string | null
    /** Total number of data points analyzed. */
    total_points: number
    /** Number of anomalies detected. */
    anomaly_count: number
    /** Per-sub-detector scores for ensemble detectors. Each entry has 'type' and 'scores' fields. */
    sub_detector_scores?: AlertSimulateResponseApiSubDetectorScoresItem[]
    /** Per-breakdown-value simulation results. Present only when the insight has breakdowns (up to 25 values). */
    breakdown_results?: BreakdownSimulationResultApi[]
}

export interface ThresholdWithAlertApi {
    readonly id: string
    readonly created_at: string
    /**
     * Optional name for the threshold.
     * @maxLength 255
     */
    name?: string
    /** Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage). For threshold-based alerts (no detector_config), at least one of lower or upper must be set. */
    configuration: InsightThresholdApi
    readonly alerts: readonly AlertApi[]
}

export interface PaginatedThresholdWithAlertListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ThresholdWithAlertApi[]
}

export type AlertsListParams = {
    /**
     * Optional. Restrict results to alerts created by the user with this UUID.
     */
    created_by?: string
    /**
     * Optional. Restrict results to alerts on this insight ID.
     */
    insight_id?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Optional. Fuzzy match against alert `name` using Postgres trigram word similarity (handles typos, transpositions, and prefix-as-you-type). Results are ordered by relevance, then creation time. Capped at 200 characters; longer queries return a 400 error.
     */
    search?: string
}

export type AlertsRetrieveParams = {
    /**
     * Relative date string for the start of the check history window (e.g. '-24h', '-7d', '-14d'). Returns checks created after this time. Max retention is 14 days.
     */
    checks_date_from?: string
    /**
     * Relative date string for the end of the check history window (e.g. '-1h', '-1d'). Defaults to now if not specified.
     */
    checks_date_to?: string
    /**
     * Maximum number of check results to return (default 5, max 500). Applied after date filtering.
     */
    checks_limit?: number
    /**
     * Number of newest checks to skip (0-based). Use with checks_limit for pagination. Default 0.
     */
    checks_offset?: number
}

export type InsightsThresholdsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
