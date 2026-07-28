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

/**
 * * `spend` - Spend
 * * `usage` - Usage
 */
export type MetricEnumApi = (typeof MetricEnumApi)[keyof typeof MetricEnumApi]

export const MetricEnumApi = {
    Spend: 'spend',
    Usage: 'usage',
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
export type BillingAlertConfigurationStateEnumApi =
    (typeof BillingAlertConfigurationStateEnumApi)[keyof typeof BillingAlertConfigurationStateEnumApi]

export const BillingAlertConfigurationStateEnumApi = {
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

export interface BillingAlertConfigurationApi {
    /** Unique identifier for this billing alert. */
    readonly id: string
    /** Organization this billing alert belongs to. */
    readonly organization_id: string
    /** Team used as the execution context for internal notification destinations. */
    readonly execution_team_id: number
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
    /** User that created this alert, or null if unavailable. */
    readonly created_by: UserBasicApi | null
    /** User that last updated this alert, or null if unavailable. */
    readonly updated_by: UserBasicApi | null
    /**
     * Display name for this billing alert.
     * @maxLength 160
     */
    name: string
    /** Optional internal description. */
    description?: string
    /** Whether scheduled checks should evaluate this alert. */
    enabled?: boolean
    /** Billing metric to evaluate: spend or usage.
     *
     * * `spend` - Spend
     * * `usage` - Usage */
    metric?: MetricEnumApi
    /**
     * Currency for spend alerts.
     * @maxLength 3
     */
    currency?: string
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
     * @minimum 1
     * @maximum 90
     */
    baseline_window_days?: number
    /**
     * @minimum 0
     * @maximum 72
     */
    evaluation_delay_hours?: number
    readonly state: BillingAlertConfigurationStateEnumApi
    /**
     * @minimum 1
     * @maximum 24
     */
    check_interval_hours?: number
    /**
     * @minimum 0
     * @maximum 720
     */
    cooldown_hours?: number
    /** @nullable */
    snooze_until?: string | null
    /** @nullable */
    readonly next_check_at: string | null
    /** @nullable */
    readonly last_checked_at: string | null
    /** @nullable */
    readonly last_notified_at: string | null
    readonly consecutive_failures: number
    /** Notification destination types configured for this alert. */
    readonly destination_types: readonly NotificationDestinationTypeEnumApi[]
    readonly created_at: string
    readonly updated_at: string
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
    /** Team used as the execution context for internal notification destinations. */
    readonly execution_team_id?: number
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
    /** User that created this alert, or null if unavailable. */
    readonly created_by?: UserBasicApi | null
    /** User that last updated this alert, or null if unavailable. */
    readonly updated_by?: UserBasicApi | null
    /**
     * Display name for this billing alert.
     * @maxLength 160
     */
    name?: string
    /** Optional internal description. */
    description?: string
    /** Whether scheduled checks should evaluate this alert. */
    enabled?: boolean
    /** Billing metric to evaluate: spend or usage.
     *
     * * `spend` - Spend
     * * `usage` - Usage */
    metric?: MetricEnumApi
    /**
     * Currency for spend alerts.
     * @maxLength 3
     */
    currency?: string
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
     * @minimum 1
     * @maximum 90
     */
    baseline_window_days?: number
    /**
     * @minimum 0
     * @maximum 72
     */
    evaluation_delay_hours?: number
    readonly state?: BillingAlertConfigurationStateEnumApi
    /**
     * @minimum 1
     * @maximum 24
     */
    check_interval_hours?: number
    /**
     * @minimum 0
     * @maximum 720
     */
    cooldown_hours?: number
    /** @nullable */
    snooze_until?: string | null
    /** @nullable */
    readonly next_check_at?: string | null
    /** @nullable */
    readonly last_checked_at?: string | null
    /** @nullable */
    readonly last_notified_at?: string | null
    readonly consecutive_failures?: number
    /** Notification destination types configured for this alert. */
    readonly destination_types?: readonly NotificationDestinationTypeEnumApi[]
    readonly created_at?: string
    readonly updated_at?: string
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
    /** When this event was recorded. */
    readonly created_at: string
    /**
     * Billing data date evaluated by this event.
     * @nullable
     */
    readonly evaluation_date: string | null
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
     * * `spend` - Spend
     * * `usage` - Usage */
    readonly metric: MetricEnumApi
    /**
     * @nullable
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    readonly current_value: string | null
    /**
     * @nullable
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    readonly baseline_value: string | null
    /**
     * @nullable
     * @pattern ^-?\d{0,14}(?:\.\d{0,6})?$
     */
    readonly absolute_delta: string | null
    /**
     * @nullable
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    readonly relative_delta_percentage: string | null
    readonly threshold_breached: boolean
    /** @nullable */
    readonly state_before: string | null
    /** @nullable */
    readonly state_after: string | null
    /** @nullable */
    readonly notification_sent_at: string | null
    readonly targets_notified: unknown
    /** @nullable */
    readonly query_duration_ms: number | null
    /** @nullable */
    readonly error_code: string | null
    /** @nullable */
    readonly error_message: string | null
    readonly reason: string
}

export interface BillingAlertCheckNowResponseApi {
    /** Evaluation event recorded by the manual check. */
    event: BillingAlertEventApi
    /** Number of destination HogFunctions queued. */
    dispatched_destinations: number
}

export interface BillingAlertCreateDestinationApi {
    /** Destination type.
     *
     * * `slack` - slack
     * * `webhook` - webhook
     * * `teams` - teams */
    type: NotificationDestinationTypeEnumApi
    /** Integration ID for the Slack workspace. Required when type=slack. */
    slack_workspace_id?: number
    /** Slack channel ID. Required when type=slack. */
    slack_channel_id?: string
    /** Human-readable channel name for display. */
    slack_channel_name?: string
    /** HTTPS endpoint to POST to. Required when type=webhook, or the Teams webhook URL when type=teams. */
    webhook_url?: string
}

export interface BillingAlertDestinationResponseApi {
    hog_function_ids: string[]
}

export interface BillingAlertDeleteDestinationApi {
    /**
     * HogFunction IDs to delete as one atomic destination group.
     * @minItems 1
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
