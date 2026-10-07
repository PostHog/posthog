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
 * * `logs` - Logs
 * * `insight` - Insight
 */
export type PlatformAlertConfigurationSourceKindEnumApi =
    (typeof PlatformAlertConfigurationSourceKindEnumApi)[keyof typeof PlatformAlertConfigurationSourceKindEnumApi]

export const PlatformAlertConfigurationSourceKindEnumApi = {
    Logs: 'logs',
    Insight: 'insight',
} as const

/**
 * * `day` - Day
 * * `week` - Week
 * * `month` - Month
 */
export type CalendarUnitEnumApi = (typeof CalendarUnitEnumApi)[keyof typeof CalendarUnitEnumApi]

export const CalendarUnitEnumApi = {
    Day: 'day',
    Week: 'week',
    Month: 'month',
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

export interface PlatformAlertApi {
    /** Unique identifier of this alert instance. */
    readonly id: string
    /** Key of the result group this instance tracks. Empty when the source does not group results. */
    readonly grouping_key: string
    /** Current state of this alert instance.
     *
     * * `not_firing` - Not firing
     * * `firing` - Firing
     * * `errored` - Errored
     * * `snoozed` - Snoozed
     * * `broken` - Broken */
    readonly state: BillingAlertConfigurationStateEnumApi
    /**
     * When the current firing started. Null when the instance is not firing.
     * @nullable
     */
    readonly firing_started_at: string | null
    /**
     * When a notification was last sent for this instance.
     * @nullable
     */
    readonly last_notified_at: string | null
    /**
     * Time until which notifications are snoozed. Null when not snoozed.
     * @nullable
     */
    readonly snooze_until: string | null
}

/**
 * Source-specific settings. The shape depends on source_kind. The bound the alert is evaluated against is under the condition key.
 */
export type PlatformAlertConfigurationApiSourceConfig = { [key: string]: unknown }

export interface PlatformAlertConfigurationApi {
    /** Unique identifier of the alert configuration. */
    readonly id: string
    /** Human-readable name of the alert. */
    readonly name: string
    /** Whether the alert is evaluated on schedule. */
    readonly enabled: boolean
    /** Product whose data the alert evaluates.
     *
     * * `logs` - Logs
     * * `insight` - Insight */
    readonly source_kind: PlatformAlertConfigurationSourceKindEnumApi
    /** Source-specific settings. The shape depends on source_kind. The bound the alert is evaluated against is under the condition key. */
    readonly source_config: PlatformAlertConfigurationApiSourceConfig
    /** Minutes between scheduled checks. Applies when recurrence_unit is null. */
    readonly check_interval_minutes: number
    /** Calendar unit the alert recurs on. Null means it recurs on check_interval_minutes.
     *
     * * `day` - Day
     * * `week` - Week
     * * `month` - Month */
    readonly recurrence_unit: CalendarUnitEnumApi | null
    /**
     * Local time (HH:MM in the project timezone) a calendar recurrence lands on. Null means the default anchor for the unit.
     * @nullable
     */
    readonly anchor_time: string | null
    /** Number of recent checks considered when deciding to fire. */
    readonly evaluation_periods: number
    /** Number of breaching checks within evaluation_periods required to fire. */
    readonly datapoints_to_alarm: number
    /** Minimum minutes between notifications for the same alert. */
    readonly cooldown_minutes: number
    /** Blocked local time windows (HH:MM in the project timezone) when the alert does not run. Null means no quiet hours. */
    readonly schedule_restriction: AlertScheduleRestrictionApi | null
    /**
     * When the next check is due. Null when no check is scheduled.
     * @nullable
     */
    readonly next_check_at: string | null
    /** Number of checks in a row that failed to evaluate. */
    readonly consecutive_failures: number
    /**
     * ID of the legacy source configuration this row was backfilled from. Null for alerts created on the platform.
     * @nullable
     */
    readonly legacy_configuration_id: string | null
    /** When the configuration was created. */
    readonly created_at: string
    /** When the configuration was last changed. */
    readonly updated_at: string
    /** Runtime state for each result group of this configuration. */
    readonly alerts: readonly PlatformAlertApi[]
}

export interface PaginatedPlatformAlertConfigurationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: PlatformAlertConfigurationApi[]
}

export type PlatformAlertsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
