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
 * * `spend` - Spend
 */
export type BillingAlertMetricEnumApi = (typeof BillingAlertMetricEnumApi)[keyof typeof BillingAlertMetricEnumApi]

export const BillingAlertMetricEnumApi = {
    Spend: 'spend',
} as const

/**
 * * `USD` - USD
 */
export type CurrencyEnumApi = (typeof CurrencyEnumApi)[keyof typeof CurrencyEnumApi]

export const CurrencyEnumApi = {
    Usd: 'USD',
} as const

/**
 * * `relative_increase` - Relative increase
 * * `absolute_value` - Absolute value
 * * `absolute_increase` - Absolute increase
 */
export type ThresholdTypeEnumApi = (typeof ThresholdTypeEnumApi)[keyof typeof ThresholdTypeEnumApi]

export const ThresholdTypeEnumApi = {
    RelativeIncrease: 'relative_increase',
    AbsoluteValue: 'absolute_value',
    AbsoluteIncrease: 'absolute_increase',
} as const

/**
 * * `not_firing` - Not firing
 * * `firing` - Firing
 * * `errored` - Errored
 * * `snoozed` - Snoozed
 * * `broken` - Broken
 */
export type BillingAlertStateEnumApi = (typeof BillingAlertStateEnumApi)[keyof typeof BillingAlertStateEnumApi]

export const BillingAlertStateEnumApi = {
    NotFiring: 'not_firing',
    Firing: 'firing',
    Errored: 'errored',
    Snoozed: 'snoozed',
    Broken: 'broken',
} as const

/**
 * * `slack` - slack
 * * `webhook` - webhook
 * * `teams` - teams
 */
export type NotificationDestinationTypeEnumApi =
    (typeof NotificationDestinationTypeEnumApi)[keyof typeof NotificationDestinationTypeEnumApi]

export const NotificationDestinationTypeEnumApi = {
    Slack: 'slack',
    Webhook: 'webhook',
    Teams: 'teams',
} as const

export interface BillingAlertDestinationSummaryApi {
    type: NotificationDestinationTypeEnumApi
    hog_function_ids: string[]
}

export interface BillingAlertDestinationCreateDataApi {
    /** Destination type.
     *
     * * `slack` - slack
     * * `webhook` - webhook
     * * `teams` - teams */
    type: NotificationDestinationTypeEnumApi
    /** Slack integration ID in the alert execution project. */
    slack_workspace_id?: number
    /** Slack channel ID for alert delivery. */
    slack_channel_id?: string
    /** Optional Slack channel name shown in the UI. */
    slack_channel_name?: string
    /** HTTPS webhook URL for webhook or Microsoft Teams delivery. */
    webhook_url?: string
}

export interface BillingAlertDestinationChangesApi {
    /**
     * @items.minItems 4
     * @items.maxItems 4
     */
    delete?: string[][]
    create?: BillingAlertDestinationCreateDataApi[]
}

export interface BillingAlertConfigurationApi {
    /** Unique identifier for this billing alert. */
    readonly id: string
    /** Organization this billing alert belongs to. */
    readonly organization_id: string
    /**
     * Team used as the execution context for internal notification destinations.
     * @nullable
     */
    readonly execution_team_id: number | null
    /**
     * User ID that created this alert.
     * @nullable
     */
    readonly created_by_id: number | null
    /**
     * User ID that last updated this alert.
     * @nullable
     */
    readonly updated_by_id: number | null
    /**
     * Display name for this billing alert.
     * @maxLength 160
     */
    name: string
    /** Optional internal description. */
    description?: string
    /** Whether scheduled checks should evaluate this alert. */
    enabled?: boolean
    /** Billing metric evaluated by this alert. The first version supports spend only.
     *
     * * `spend` - Spend */
    readonly metric: BillingAlertMetricEnumApi
    /** Server-controlled currency for spend values.
     *
     * * `USD` - USD */
    readonly currency: CurrencyEnumApi
    /** Revision incremented whenever evaluation behavior changes. */
    readonly configuration_revision: number
    /** Threshold rule type.
     *
     * * `relative_increase` - Relative increase
     * * `absolute_value` - Absolute value
     * * `absolute_increase` - Absolute increase */
    threshold_type?: ThresholdTypeEnumApi
    /**
     * Percentage increase that triggers relative increase alerts.
     * @nullable
     * @pattern ^-?\d{0,6}(?:\.\d{0,2})?$
     */
    threshold_percentage?: string | null
    /**
     * Absolute value or absolute increase that triggers absolute threshold alerts.
     * @nullable
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    threshold_value?: string | null
    /**
     * Minimum current value before the alert can fire.
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    minimum_value?: string
    /**
     * Number of preceding UTC billing dates averaged for relative and absolute increase baselines.
     * @minimum 1
     * @maximum 90
     */
    baseline_window_days?: number
    /**
     * Hours after a UTC billing date ends before it becomes eligible for evaluation.
     * @minimum 0
     * @maximum 72
     */
    evaluation_delay_hours?: number
    /** Current lifecycle state of this alert.
     *
     * * `not_firing` - Not firing
     * * `firing` - Firing
     * * `errored` - Errored
     * * `snoozed` - Snoozed
     * * `broken` - Broken */
    readonly state: BillingAlertStateEnumApi
    /**
     * Minimum hours between repeated firing notifications.
     * @minimum 0
     * @maximum 720
     */
    cooldown_hours?: number
    /**
     * ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.
     * @nullable
     */
    snoozed_until?: string | null
    /**
     * When the next scheduled evaluation is due.
     * @nullable
     */
    readonly next_check_at: string | null
    /**
     * When this alert was last evaluated.
     * @nullable
     */
    readonly last_checked_at: string | null
    /**
     * When notifications were last delivered for this alert.
     * @nullable
     */
    readonly last_notified_at: string | null
    /** Number of consecutive failed evaluations. */
    readonly consecutive_failures: number
    /** Notification destination groups configured for this alert, including their shared HogFunctions. */
    readonly destinations: readonly BillingAlertDestinationSummaryApi[]
    /** Destination groups to create or delete in the same transaction as this configuration write. */
    destination_changes?: BillingAlertDestinationChangesApi
    /** When this alert was created. */
    readonly created_at: string
    /**
     * When this alert was last updated.
     * @nullable
     */
    readonly updated_at: string | null
}

export interface PaginatedBillingAlertConfigurationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BillingAlertConfigurationApi[]
}

export interface PatchedBillingAlertConfigurationApi {
    /** Unique identifier for this billing alert. */
    readonly id?: string
    /** Organization this billing alert belongs to. */
    readonly organization_id?: string
    /**
     * Team used as the execution context for internal notification destinations.
     * @nullable
     */
    readonly execution_team_id?: number | null
    /**
     * User ID that created this alert.
     * @nullable
     */
    readonly created_by_id?: number | null
    /**
     * User ID that last updated this alert.
     * @nullable
     */
    readonly updated_by_id?: number | null
    /**
     * Display name for this billing alert.
     * @maxLength 160
     */
    name?: string
    /** Optional internal description. */
    description?: string
    /** Whether scheduled checks should evaluate this alert. */
    enabled?: boolean
    /** Billing metric evaluated by this alert. The first version supports spend only.
     *
     * * `spend` - Spend */
    readonly metric?: BillingAlertMetricEnumApi
    /** Server-controlled currency for spend values.
     *
     * * `USD` - USD */
    readonly currency?: CurrencyEnumApi
    /** Revision incremented whenever evaluation behavior changes. */
    readonly configuration_revision?: number
    /** Threshold rule type.
     *
     * * `relative_increase` - Relative increase
     * * `absolute_value` - Absolute value
     * * `absolute_increase` - Absolute increase */
    threshold_type?: ThresholdTypeEnumApi
    /**
     * Percentage increase that triggers relative increase alerts.
     * @nullable
     * @pattern ^-?\d{0,6}(?:\.\d{0,2})?$
     */
    threshold_percentage?: string | null
    /**
     * Absolute value or absolute increase that triggers absolute threshold alerts.
     * @nullable
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    threshold_value?: string | null
    /**
     * Minimum current value before the alert can fire.
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    minimum_value?: string
    /**
     * Number of preceding UTC billing dates averaged for relative and absolute increase baselines.
     * @minimum 1
     * @maximum 90
     */
    baseline_window_days?: number
    /**
     * Hours after a UTC billing date ends before it becomes eligible for evaluation.
     * @minimum 0
     * @maximum 72
     */
    evaluation_delay_hours?: number
    /** Current lifecycle state of this alert.
     *
     * * `not_firing` - Not firing
     * * `firing` - Firing
     * * `errored` - Errored
     * * `snoozed` - Snoozed
     * * `broken` - Broken */
    readonly state?: BillingAlertStateEnumApi
    /**
     * Minimum hours between repeated firing notifications.
     * @minimum 0
     * @maximum 720
     */
    cooldown_hours?: number
    /**
     * ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.
     * @nullable
     */
    snoozed_until?: string | null
    /**
     * When the next scheduled evaluation is due.
     * @nullable
     */
    readonly next_check_at?: string | null
    /**
     * When this alert was last evaluated.
     * @nullable
     */
    readonly last_checked_at?: string | null
    /**
     * When notifications were last delivered for this alert.
     * @nullable
     */
    readonly last_notified_at?: string | null
    /** Number of consecutive failed evaluations. */
    readonly consecutive_failures?: number
    /** Notification destination groups configured for this alert, including their shared HogFunctions. */
    readonly destinations?: readonly BillingAlertDestinationSummaryApi[]
    /** Destination groups to create or delete in the same transaction as this configuration write. */
    destination_changes?: BillingAlertDestinationChangesApi
    /** When this alert was created. */
    readonly created_at?: string
    /**
     * When this alert was last updated.
     * @nullable
     */
    readonly updated_at?: string | null
}

/**
 * * `check` - Check
 * * `firing` - Firing
 * * `resolved` - Resolved
 * * `errored` - Errored
 * * `broken_config` - Broken config
 */
export type BillingAlertEventKindEnumApi =
    (typeof BillingAlertEventKindEnumApi)[keyof typeof BillingAlertEventKindEnumApi]

export const BillingAlertEventKindEnumApi = {
    Check: 'check',
    Firing: 'firing',
    Resolved: 'resolved',
    Errored: 'errored',
    BrokenConfig: 'broken_config',
} as const

/**
 * * `scheduled` - Scheduled
 * * `manual` - Manual
 */
export type BillingAlertEventSourceEnumApi =
    (typeof BillingAlertEventSourceEnumApi)[keyof typeof BillingAlertEventSourceEnumApi]

export const BillingAlertEventSourceEnumApi = {
    Scheduled: 'scheduled',
    Manual: 'manual',
} as const

export interface BillingAlertEventApi {
    /** Unique identifier for this billing alert event. */
    readonly id: string
    /** Event kind for a check, state transition, or delivery-worthy alert event.
     *
     * * `check` - Check
     * * `firing` - Firing
     * * `resolved` - Resolved
     * * `errored` - Errored
     * * `broken_config` - Broken config */
    readonly kind: BillingAlertEventKindEnumApi
    /** Whether this evaluation was scheduled or manually requested.
     *
     * * `scheduled` - Scheduled
     * * `manual` - Manual */
    readonly source: BillingAlertEventSourceEnumApi
    /** Attempt number for this billing date and configuration revision. */
    readonly attempt_number: number
    /** When this event was recorded. */
    readonly created_at: string
    /**
     * Billing data date evaluated by this event.
     * @nullable
     */
    readonly evaluation_date: string | null
    /** Configuration revision used for this evaluation. */
    readonly configuration_revision: number
    /**
     * Start of the evaluated billing period.
     * @nullable
     */
    readonly period_start: string | null
    /**
     * End of the evaluated billing period.
     * @nullable
     */
    readonly period_end: string | null
    /** Billing metric evaluated by this event.
     *
     * * `spend` - Spend */
    readonly metric: BillingAlertMetricEnumApi
    /**
     * Metric value for the evaluated billing date.
     * @nullable
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    readonly current_value: string | null
    /**
     * Average metric value across the baseline window.
     * @nullable
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    readonly baseline_value: string | null
    /**
     * Current value minus the baseline value.
     * @nullable
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    readonly absolute_delta: string | null
    /**
     * Percentage change against the baseline value.
     * @nullable
     * @pattern ^-?\d{0,22}(?:\.\d{0,6})?$
     */
    readonly relative_delta_percentage: string | null
    /** Whether the evaluated value breached the configured threshold. */
    readonly threshold_breached: boolean
    /** Alert state before this event was applied.
     *
     * * `not_firing` - Not firing
     * * `firing` - Firing
     * * `errored` - Errored
     * * `snoozed` - Snoozed
     * * `broken` - Broken */
    readonly state_before: BillingAlertStateEnumApi | null
    /** Alert state after this event was applied.
     *
     * * `not_firing` - Not firing
     * * `firing` - Firing
     * * `errored` - Errored
     * * `snoozed` - Snoozed
     * * `broken` - Broken */
    readonly state_after: BillingAlertStateEnumApi | null
    /**
     * When notifications for this event were delivered.
     * @nullable
     */
    readonly notification_sent_at: string | null
    /** Notification targets recorded for this event. */
    readonly targets_notified: unknown
    /**
     * Milliseconds spent fetching billing data for this evaluation.
     * @nullable
     */
    readonly query_duration_ms: number | null
    /**
     * Exception class name recorded when the evaluation failed.
     * @nullable
     */
    readonly error_code: string | null
    /**
     * Failure description recorded when the evaluation failed.
     * @nullable
     */
    readonly error_message: string | null
    /** Human-readable explanation of the evaluation outcome. */
    readonly reason: string
}

export interface BillingAlertCheckNowResponseApi {
    /** Evaluation event recorded by the manual check. */
    event: BillingAlertEventApi
    /** Number of destination HogFunctions queued. */
    dispatched_destinations: number
}

export interface BillingAlertDestinationResponseApi {
    hog_function_ids: string[]
}

export interface BillingAlertDeleteDestinationApi {
    /**
     * HogFunction IDs to delete as one atomic destination group.
     * @minItems 4
     * @maxItems 4
     */
    hog_function_ids: string[]
}

export interface PaginatedBillingAlertEventListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BillingAlertEventApi[]
}

export type BillingAlertsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type BillingAlertsEventsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
