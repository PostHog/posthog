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
    /** @nullable */
    lower?: number | null
    /** @nullable */
    upper?: number | null
}

export type InsightThresholdTypeApi = (typeof InsightThresholdTypeApi)[keyof typeof InsightThresholdTypeApi]

export const InsightThresholdTypeApi = {
    Absolute: 'absolute',
    Percentage: 'percentage',
} as const

export interface InsightThresholdApi {
    bounds?: InsightsThresholdBoundsApi | null
    type: InsightThresholdTypeApi
}

export interface ThresholdApi {
    readonly id: string
    readonly created_at: string
    /** @maxLength 255 */
    name?: string
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
export type State66aEnumApi = (typeof State66aEnumApi)[keyof typeof State66aEnumApi]

export const State66aEnumApi = {
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
    readonly state: State66aEnumApi
    readonly targets_notified: boolean
}

export type TrendsAlertConfigApiType = (typeof TrendsAlertConfigApiType)[keyof typeof TrendsAlertConfigApiType]

export const TrendsAlertConfigApiType = {
    TrendsAlertConfig: 'TrendsAlertConfig',
} as const

export interface TrendsAlertConfigApi {
    /** @nullable */
    check_ongoing_interval?: boolean | null
    series_index: number
    type?: TrendsAlertConfigApiType
}

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
    /** @maxLength 255 */
    name?: string
    /** User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object. */
    subscribed_users: number[]
    threshold: ThresholdApi
    condition?: AlertConditionApi | null
    readonly state: State66aEnumApi
    enabled?: boolean
    /** @nullable */
    readonly last_notified_at: string | null
    /** @nullable */
    readonly last_checked_at: string | null
    /** @nullable */
    readonly next_check_at: string | null
    readonly checks: readonly AlertCheckApi[]
    config?: TrendsAlertConfigApi | null
    calculation_interval?: CalculationIntervalEnumApi | BlankEnumApi | NullEnumApi | null
    /** @nullable */
    snoozed_until?: string | null
    /** @nullable */
    skip_weekend?: boolean | null
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
    /** @maxLength 255 */
    name?: string
    /** User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object. */
    subscribed_users?: number[]
    threshold?: ThresholdApi
    condition?: AlertConditionApi | null
    readonly state?: State66aEnumApi
    enabled?: boolean
    /** @nullable */
    readonly last_notified_at?: string | null
    /** @nullable */
    readonly last_checked_at?: string | null
    /** @nullable */
    readonly next_check_at?: string | null
    readonly checks?: readonly AlertCheckApi[]
    config?: TrendsAlertConfigApi | null
    calculation_interval?: CalculationIntervalEnumApi | BlankEnumApi | NullEnumApi | null
    /** @nullable */
    snoozed_until?: string | null
    /** @nullable */
    skip_weekend?: boolean | null
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
