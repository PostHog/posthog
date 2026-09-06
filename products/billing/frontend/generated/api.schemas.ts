/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type BillingOverviewResponseApiProductsItem = { [key: string]: unknown }

export interface BillingOverviewResponseApi {
    /** @nullable */
    customer_id?: string | null
    /** @nullable */
    billing_plan?: string | null
    /** @nullable */
    subscription_level?: string | null
    has_active_subscription?: boolean
    deactivated?: boolean
    is_annual_plan_customer?: boolean
    /** @nullable */
    free_trial_until?: string | null
    /** @nullable */
    current_total_amount_usd?: string | null
    /** @nullable */
    current_total_amount_usd_after_discount?: string | null
    /** @nullable */
    projected_total_amount_usd?: string | null
    /** @nullable */
    projected_total_amount_usd_after_discount?: string | null
    /** @nullable */
    projected_total_amount_usd_with_limit?: string | null
    /** @nullable */
    projected_total_amount_usd_with_limit_after_discount?: string | null
    /** @nullable */
    discount_amount_usd?: string | null
    /** @nullable */
    discount_percent?: number | null
    /** @nullable */
    amount_off_expires_at?: string | null
    /** @nullable */
    startup_program_label?: string | null
    /** @nullable */
    startup_program_label_previous?: string | null
    stripe_portal_url?: string | null
    external_billing_provider_invoices_url?: string | null
    /** Subscribed and available products/addons with pricing, plan, limit, usage, and entitlement metadata. */
    products?: BillingOverviewResponseApiProductsItem[]
    available_product_features?: string[]
    usage_summary?: unknown
    billing_period?: unknown
    custom_limits_usd?: unknown
    next_period_custom_limits_usd?: unknown
    trial?: unknown
    license?: unknown
    account_owner?: unknown
    customer_trust_scores?: unknown
    never_drop_data?: boolean
}

export interface BillingApi {
    /** @maxLength 100 */
    plan: string
    billing_limit: number
}

export interface PatchedBillingApi {
    /** @maxLength 100 */
    plan?: string
    billing_limit?: number
}

export interface BillingPeriodResponseApi {
    /**
     * Start of the organization's current billing period, or null when billing has not synced a period.
     * @nullable
     */
    current_period_start: string | null
    /**
     * End of the organization's current billing period, or null when billing has not synced a period.
     * @nullable
     */
    current_period_end: string | null
}

/**
 * * `type` - type
 * * `team` - team
 * * `multiple` - multiple
 */
export type BreakdownTypeEnumApi = (typeof BreakdownTypeEnumApi)[keyof typeof BreakdownTypeEnumApi]

export const BreakdownTypeEnumApi = {
    Type: 'type',
    Team: 'team',
    Multiple: 'multiple',
} as const

export interface BillingTimeSeriesPointApi {
    id?: number
    label?: string
    data?: number[]
    dates?: string[]
    breakdown_type?: BreakdownTypeEnumApi | null
    breakdown_value?: unknown
}

export interface BillingTimeSeriesResponseApi {
    status?: string
    type?: string
    customer_id?: number
    results: BillingTimeSeriesPointApi[]
    team_id_options?: number[]
    next?: string
}

/**
 * * `spend` - Spend
 * * `projected_spend` - Projected spend
 */
export type BillingAlertConfigurationMetricEnumApi =
    (typeof BillingAlertConfigurationMetricEnumApi)[keyof typeof BillingAlertConfigurationMetricEnumApi]

export const BillingAlertConfigurationMetricEnumApi = {
    Spend: 'spend',
    ProjectedSpend: 'projected_spend',
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
export type BillingAlertConfigurationThresholdTypeEnumApi =
    (typeof BillingAlertConfigurationThresholdTypeEnumApi)[keyof typeof BillingAlertConfigurationThresholdTypeEnumApi]

export const BillingAlertConfigurationThresholdTypeEnumApi = {
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
     * @items.minItems 1
     * @items.maxItems 100
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
    /** Billing-period total to evaluate: current spend so far, or projected period-end spend.
     *
     * * `spend` - Spend
     * * `projected_spend` - Projected spend */
    metric?: BillingAlertConfigurationMetricEnumApi
    /** Server-controlled currency for spend values.
     *
     * * `USD` - USD */
    readonly currency: CurrencyEnumApi
    /** Revision incremented whenever evaluation behavior changes. */
    readonly configuration_revision: number
    /** Threshold rule type. The first version supports absolute value only.
     *
     * * `relative_increase` - Relative increase
     * * `absolute_value` - Absolute value
     * * `absolute_increase` - Absolute increase */
    threshold_type?: BillingAlertConfigurationThresholdTypeEnumApi
    /**
     * Reserved for future increase-over-baseline rules. Not used by absolute value alerts.
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
     * Reserved for future increase-over-baseline rules. Not used by absolute value alerts.
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
    readonly state: BillingAlertConfigurationStateEnumApi
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
    /** Billing-period total to evaluate: current spend so far, or projected period-end spend.
     *
     * * `spend` - Spend
     * * `projected_spend` - Projected spend */
    metric?: BillingAlertConfigurationMetricEnumApi
    /** Server-controlled currency for spend values.
     *
     * * `USD` - USD */
    readonly currency?: CurrencyEnumApi
    /** Revision incremented whenever evaluation behavior changes. */
    readonly configuration_revision?: number
    /** Threshold rule type. The first version supports absolute value only.
     *
     * * `relative_increase` - Relative increase
     * * `absolute_value` - Absolute value
     * * `absolute_increase` - Absolute increase */
    threshold_type?: BillingAlertConfigurationThresholdTypeEnumApi
    /**
     * Reserved for future increase-over-baseline rules. Not used by absolute value alerts.
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
     * Reserved for future increase-over-baseline rules. Not used by absolute value alerts.
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
    readonly state?: BillingAlertConfigurationStateEnumApi
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
     * * `spend` - Spend
     * * `projected_spend` - Projected spend */
    readonly metric: BillingAlertConfigurationMetricEnumApi
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
    readonly state_before: BillingAlertConfigurationStateEnumApi | null
    /** Alert state after this event was applied.
     *
     * * `not_firing` - Not firing
     * * `firing` - Firing
     * * `errored` - Errored
     * * `snoozed` - Snoozed
     * * `broken` - Broken */
    readonly state_after: BillingAlertConfigurationStateEnumApi | null
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
    /** Evaluation event recorded by the manual check, or null for a paused preview. */
    event?: BillingAlertEventApi | null
    /** Number of destination HogFunctions queued. */
    dispatched_destinations: number
    /** True when the alert is paused: it was evaluated but no notifications were sent. */
    preview: boolean
    /** Whether the evaluated billing-period total breached the configured threshold. */
    threshold_breached: boolean
    /**
     * Evaluated billing-period total, or null when billing data was not available.
     * @nullable
     */
    current_value?: string | null
}

export interface BillingAlertDestinationResponseApi {
    hog_function_ids: string[]
}

export interface BillingAlertDeleteDestinationApi {
    /**
     * HogFunction IDs to delete as one atomic destination group.
     * @minItems 1
     * @maxItems 100
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

export interface ProductFeatureApi {
    key: string
    name: string
    description: string
    /** @nullable */
    unit?: string | null
    /** @nullable */
    limit?: number | null
    /** @nullable */
    note?: string | null
    is_plan_default?: boolean
    /** @nullable */
    entitlement_only?: boolean | null
    /** @nullable */
    category?: string | null
}

export interface BillingFeaturesApi {
    available_product_features: ProductFeatureApi[]
}

/**
 * * `month` - month
 * * `year` - year
 */
export type BillingPeriodIntervalEnumApi =
    (typeof BillingPeriodIntervalEnumApi)[keyof typeof BillingPeriodIntervalEnumApi]

export const BillingPeriodIntervalEnumApi = {
    Month: 'month',
    Year: 'year',
} as const

export interface BillingPeriodApi {
    current_period_start: string
    current_period_end: string
    interval: BillingPeriodIntervalEnumApi
}

/**
 * * `product` - Product
 * * `addon` - Addon
 */
export type CatalogKindEnumApi = (typeof CatalogKindEnumApi)[keyof typeof CatalogKindEnumApi]

export const CatalogKindEnumApi = {
    Product: 'product',
    Addon: 'addon',
} as const

export interface TierForecastApi {
    /** @nullable */
    up_to: number | null
    /** @nullable */
    projected_usage: number | null
    /** @nullable */
    projected_amount_usd: string | null
}

export interface ForecastItemApi {
    kind: CatalogKindEnumApi
    key: string
    /** @nullable */
    usage_key: string | null
    /** @nullable */
    projected_usage: number | null
    /** @nullable */
    projected_amount_usd: string | null
    /** @nullable */
    projected_amount_usd_with_limit?: string | null
    /** @nullable */
    tier_forecast: TierForecastApi[] | null
}

export interface ProductForecastApi {
    kind: CatalogKindEnumApi
    key: string
    /** @nullable */
    usage_key: string | null
    /** @nullable */
    projected_usage: number | null
    /** @nullable */
    projected_amount_usd: string | null
    /** @nullable */
    projected_amount_usd_with_limit?: string | null
    /** @nullable */
    tier_forecast: TierForecastApi[] | null
    addons: ForecastItemApi[]
}

export interface BillingForecastApi {
    billing_period: BillingPeriodApi | null
    /** @nullable */
    projected_total_amount_usd: string | null
    /** @nullable */
    projected_total_amount_usd_with_limit: string | null
    /** @nullable */
    projected_total_amount_usd_after_discount: string | null
    /** @nullable */
    projected_total_amount_usd_with_limit_after_discount: string | null
    products: ProductForecastApi[]
    computed_at: string
}

/**
 * * `open` - open
 * * `paid` - paid
 * * `uncollectible` - uncollectible
 * * `void` - void
 */
export type BillingInvoiceStatusEnumApi = (typeof BillingInvoiceStatusEnumApi)[keyof typeof BillingInvoiceStatusEnumApi]

export const BillingInvoiceStatusEnumApi = {
    Open: 'open',
    Paid: 'paid',
    Uncollectible: 'uncollectible',
    Void: 'void',
} as const

export interface BillingInvoiceApi {
    id: string
    /** @nullable */
    number: string | null
    status: BillingInvoiceStatusEnumApi
    /** @nullable */
    currency: string | null
    subtotal: string
    total: string
    amount_due: string
    amount_paid: string
    period_start: string
    period_end: string
    /** @nullable */
    created: string | null
    /** @nullable */
    due_date: string | null
}

export interface BillingInvoicesApi {
    /** @nullable */
    next: string | null
    /** @nullable */
    previous: string | null
    results: BillingInvoiceApi[]
}

export interface ProductLimitApi {
    key: string
    /** @nullable */
    limit_usd: number | null
    /** @nullable */
    next_period_limit_usd: number | null
    /** @nullable */
    spend_usd: string | null
    reached: boolean
}

export interface BillingLimitsApi {
    results: ProductLimitApi[]
}

export interface PriceTierApi {
    flat_amount_usd: string
    unit_amount_usd: string
    /** @nullable */
    up_to: number | null
}

export interface ProductPlanApi {
    product_key: string
    plan_key: string
    name: string
    description: string
    /** @nullable */
    image_url: string | null
    /** @nullable */
    docs_url: string | null
    /** @nullable */
    note: string | null
    /** @nullable */
    unit: string | null
    flat_rate: boolean
    /** @nullable */
    tiers: PriceTierApi[] | null
    /** @nullable */
    free_allocation: number | null
    features: ProductFeatureApi[]
    /** @nullable */
    included_if: string | null
    /** @nullable */
    contact_support: boolean | null
    /** @nullable */
    unit_amount_usd: string | null
    current_plan: boolean
    /** @nullable */
    initial_billing_limit?: number | null
}

export interface ProductBaseFeatureApi {
    key: string
    name: string
    description: string
    images?: unknown
    /** @nullable */
    icon_key?: string | null
    /** @nullable */
    type?: string | null
    /** @nullable */
    category?: string | null
}

export interface ProductTrialConfigApi {
    length: number
}

export interface BillingAddonApi {
    kind: CatalogKindEnumApi
    key: string
    /** @nullable */
    usage_key: string | null
    name: string
    description: string
    /** @nullable */
    price_description: string | null
    /** @nullable */
    icon_key: string | null
    /** @nullable */
    image_url: string | null
    /** @nullable */
    docs_url: string | null
    /** @nullable */
    subscribed: boolean | null
    inclusion_only: boolean
    /** @nullable */
    contact_support: boolean | null
    /** @nullable */
    legacy_product: boolean | null
    /** @nullable */
    free_allocation: number | null
    /** @nullable */
    usage_limit: number | null
    /** @nullable */
    unit: string | null
    /** @nullable */
    display_unit: string | null
    /** @nullable */
    display_decimals: number | null
    /** @nullable */
    display_divisor: number | null
    tiered: boolean
    /** @nullable */
    unit_amount_usd: string | null
    /** @nullable */
    tiers: PriceTierApi[] | null
    plans?: ProductPlanApi[]
    features: ProductBaseFeatureApi[]
    trial: ProductTrialConfigApi | null
    included_with_main_product: boolean
    /** @nullable */
    included_if: string | null
    /** @nullable */
    default_unit_amount_usd: string | null
}

export interface BillingProductApi {
    kind: CatalogKindEnumApi
    key: string
    /** @nullable */
    usage_key: string | null
    name: string
    description: string
    /** @nullable */
    price_description: string | null
    /** @nullable */
    icon_key: string | null
    /** @nullable */
    image_url: string | null
    /** @nullable */
    docs_url: string | null
    /** @nullable */
    subscribed: boolean | null
    inclusion_only: boolean
    /** @nullable */
    contact_support: boolean | null
    /** @nullable */
    legacy_product: boolean | null
    /** @nullable */
    free_allocation: number | null
    /** @nullable */
    usage_limit: number | null
    /** @nullable */
    unit: string | null
    /** @nullable */
    display_unit: string | null
    /** @nullable */
    display_decimals: number | null
    /** @nullable */
    display_divisor: number | null
    tiered: boolean
    /** @nullable */
    unit_amount_usd: string | null
    /** @nullable */
    tiers: PriceTierApi[] | null
    plans?: ProductPlanApi[]
    features: ProductBaseFeatureApi[]
    trial: ProductTrialConfigApi | null
    /** @nullable */
    headline: string | null
    /** @nullable */
    screenshot_url: string | null
    addons: BillingAddonApi[]
}

export interface BillingProductsApi {
    results: BillingProductApi[]
}

export interface TierSpendApi {
    /** @nullable */
    up_to: number | null
    /** @nullable */
    current_amount_usd: string | null
}

export interface SpendItemApi {
    kind: CatalogKindEnumApi
    key: string
    /** @nullable */
    usage_key: string | null
    /** @nullable */
    current_amount_usd: string | null
    /** @nullable */
    current_amount_usd_before_addons?: string | null
    /** @nullable */
    tier_spend: TierSpendApi[] | null
}

export interface ProductSpendApi {
    kind: CatalogKindEnumApi
    key: string
    /** @nullable */
    usage_key: string | null
    /** @nullable */
    current_amount_usd: string | null
    /** @nullable */
    current_amount_usd_before_addons?: string | null
    /** @nullable */
    tier_spend: TierSpendApi[] | null
    addons: SpendItemApi[]
}

export interface BillingSpendSummaryApi {
    billing_period: BillingPeriodApi | null
    /** @nullable */
    usage_reported_through: string | null
    /** @nullable */
    current_total_amount_usd: string | null
    /** @nullable */
    current_total_amount_usd_after_discount: string | null
    products: ProductSpendApi[]
}

export interface PaginatedBillingTimeSeriesPointListApi {
    count: number
    /** @nullable */
    next: string | null
    /** @nullable */
    previous: string | null
    results: BillingTimeSeriesPointApi[]
}

/**
 * * `stripe` - stripe
 * * `vercel` - vercel
 */
export type BillingProviderEnumApi = (typeof BillingProviderEnumApi)[keyof typeof BillingProviderEnumApi]

export const BillingProviderEnumApi = {
    Stripe: 'stripe',
    Vercel: 'vercel',
} as const

export interface TrialApi {
    type: string
    status: string
    target: string
    /** @nullable */
    expires_at: string | null
}

export interface LicenseApi {
    plan: string
}

export interface BillingSubscriptionApi {
    /** @nullable */
    customer_id: string | null
    has_active_subscription: boolean
    /** @nullable */
    subscription_level: string | null
    /** @nullable */
    billing_plan: string | null
    billing_provider: BillingProviderEnumApi | null
    deactivated: boolean
    is_annual_plan_customer: boolean
    billing_period: BillingPeriodApi | null
    trial: TrialApi | null
    /** @nullable */
    free_trial_until: string | null
    /** @nullable */
    discount_percent: number | null
    /** @nullable */
    discount_amount_usd: string | null
    /** @nullable */
    amount_off_expires_at: string | null
    /** @nullable */
    startup_program_label: string | null
    /** @nullable */
    startup_program_label_previous: string | null
    billing_portal_url: string
    invoices_url?: string
    license: LicenseApi
}

export interface UsageKeySummaryApi {
    usage_key: string
    /** @nullable */
    usage: number | null
    /** @nullable */
    limit: number | null
    /** @nullable */
    todays_usage?: number | null
    /** @nullable */
    quota_limited_until: string | null
    /** @nullable */
    quota_limiting_suspended_until: string | null
}

export interface TierUsageApi {
    /** @nullable */
    up_to: number | null
    current_usage: number
}

export interface UsageItemApi {
    kind: CatalogKindEnumApi
    key: string
    /** @nullable */
    usage_key: string | null
    current_usage: number
    /** @nullable */
    usage_limit: number | null
    has_exceeded_limit: boolean
    usage_ratio: number
    /** @nullable */
    tier_usage: TierUsageApi[] | null
}

export interface ProductUsageApi {
    kind: CatalogKindEnumApi
    key: string
    /** @nullable */
    usage_key: string | null
    current_usage: number
    /** @nullable */
    usage_limit: number | null
    has_exceeded_limit: boolean
    usage_ratio: number
    /** @nullable */
    tier_usage: TierUsageApi[] | null
    addons: UsageItemApi[]
}

export interface BillingUsageSummaryApi {
    billing_period: BillingPeriodApi | null
    /** @nullable */
    usage_reported_through: string | null
    usage_summary: UsageKeySummaryApi[]
    products: ProductUsageApi[]
}

export type BillingSpendRetrieveParams = {
    /**
     * JSON-encoded array of breakdown dimensions. Valid values are "type" and "team", for example ["type","team"]. Omit for a single aggregate series.
     * @nullable
     */
    breakdowns?: string | null
    /**
     * @nullable
     */
    end_date?: string | null
    /**
     * @nullable
     */
    interval?: string | null
    /**
     * @nullable
     */
    start_date?: string | null
    /**
     * JSON-encoded array of numeric team/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.
     * @nullable
     */
    team_ids?: string | null
    /**
     * JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period, logs_retention_30d_mb_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. ["event_count_in_period","recording_count_in_period"]. Omit for all types.
     * @nullable
     */
    usage_types?: string | null
}

export type BillingUsageRetrieveParams = {
    /**
     * JSON-encoded array of breakdown dimensions. Valid values are "type" and "team", for example ["type","team"]. Omit for a single aggregate series.
     * @nullable
     */
    breakdowns?: string | null
    /**
     * @nullable
     */
    end_date?: string | null
    /**
     * @nullable
     */
    interval?: string | null
    /**
     * @nullable
     */
    start_date?: string | null
    /**
     * JSON-encoded array of numeric team/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.
     * @nullable
     */
    team_ids?: string | null
    /**
     * JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period, logs_retention_30d_mb_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. ["event_count_in_period","recording_count_in_period"]. Omit for all types.
     * @nullable
     */
    usage_types?: string | null
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

export type BillingInvoicesListParams = {
    /**
     * The cursor from a previous page.
     * @minLength 1
     */
    cursor?: string
    /**
     * Invoices per page.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Only invoices in this state.
     *
     * * `open` - open
     * * `paid` - paid
     * * `uncollectible` - uncollectible
     * * `void` - void
     * @minLength 1
     */
    status?: BillingInvoicesListStatus
}

export type BillingInvoicesListStatus = (typeof BillingInvoicesListStatus)[keyof typeof BillingInvoicesListStatus]

export const BillingInvoicesListStatus = {
    Open: 'open',
    Paid: 'paid',
    Uncollectible: 'uncollectible',
    Void: 'void',
} as const

export type BillingProductsListParams = {
    /**
     * Add the `plans` list to each product and add-on. Most of the payload.
     */
    include_plans?: boolean
}

export type BillingProductsRetrieveParams = {
    /**
     * Add the `plans` list to each product and add-on. Most of the payload.
     */
    include_plans?: boolean
}

export type BillingSpendTimeseriesRetrieveParams = {
    /**
     * JSON-encoded array of breakdown dimensions. Valid values are "type" and "team", for example ["type","team"]. Omit for a single aggregate series.
     * @nullable
     */
    breakdowns?: string | null
    /**
     * @nullable
     */
    end_date?: string | null
    /**
     * @nullable
     */
    interval?: string | null
    /**
     * Series per page.
     */
    limit?: number
    /**
     * Series to skip.
     */
    offset?: number
    /**
     * @nullable
     */
    start_date?: string | null
    /**
     * JSON-encoded array of numeric team/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.
     * @nullable
     */
    team_ids?: string | null
    /**
     * JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period, logs_retention_30d_mb_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. ["event_count_in_period","recording_count_in_period"]. Omit for all types.
     * @nullable
     */
    usage_types?: string | null
}

export type BillingUsageTimeseriesRetrieveParams = {
    /**
     * JSON-encoded array of breakdown dimensions. Valid values are "type" and "team", for example ["type","team"]. Omit for a single aggregate series.
     * @nullable
     */
    breakdowns?: string | null
    /**
     * @nullable
     */
    end_date?: string | null
    /**
     * @nullable
     */
    interval?: string | null
    /**
     * Series per page.
     */
    limit?: number
    /**
     * Series to skip.
     */
    offset?: number
    /**
     * @nullable
     */
    start_date?: string | null
    /**
     * JSON-encoded array of numeric team/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.
     * @nullable
     */
    team_ids?: string | null
    /**
     * JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period, logs_retention_30d_mb_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. ["event_count_in_period","recording_count_in_period"]. Omit for all types.
     * @nullable
     */
    usage_types?: string | null
}
