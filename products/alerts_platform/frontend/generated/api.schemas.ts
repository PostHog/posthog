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
 * * `single` - Single
 * * `by_result_labels` - By result labels
 */
export type GroupingModeEnumApi = (typeof GroupingModeEnumApi)[keyof typeof GroupingModeEnumApi]

export const GroupingModeEnumApi = {
    Single: 'single',
    ByResultLabels: 'by_result_labels',
} as const

/**
 * * `degrade_visible` - Degrade visible
 */
export type OnOverflowEnumApi = (typeof OnOverflowEnumApi)[keyof typeof OnOverflowEnumApi]

export const OnOverflowEnumApi = {
    DegradeVisible: 'degrade_visible',
} as const

export interface GroupingApi {
    /** single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.
     *
     * * `single` - Single
     * * `by_result_labels` - By result labels */
    mode: GroupingModeEnumApi
    /** Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message. */
    keys?: string[]
    /**
     * Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.
     * @minimum 1
     * @maximum 100
     */
    max_instances?: number
    /** What happens to groups past max_instances. degrade_visible names how many were left out.
     *
     * * `degrade_visible` - Degrade visible */
    on_overflow?: OnOverflowEnumApi
}

/**
 * * `ok` - OK
 * * `errored` - Errored
 * * `broken` - Broken
 */
export type PlatformAlertCheckStatusEnumApi =
    (typeof PlatformAlertCheckStatusEnumApi)[keyof typeof PlatformAlertCheckStatusEnumApi]

export const PlatformAlertCheckStatusEnumApi = {
    Ok: 'ok',
    Errored: 'errored',
    Broken: 'broken',
} as const

/**
 * * `source` - Source
 * * `platform` - Platform
 */
export type PlatformAlertOwnerEnumApi = (typeof PlatformAlertOwnerEnumApi)[keyof typeof PlatformAlertOwnerEnumApi]

export const PlatformAlertOwnerEnumApi = {
    Source: 'source',
    Platform: 'platform',
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
 * Result labels and their values for the group this instance tracks, such as {"service_name": "checkout"}. Empty when the source does not group results.
 */
export type PlatformAlertApiLabels = { [key: string]: string }

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
    /** Result labels and their values for the group this instance tracks, such as {"service_name": "checkout"}. Empty when the source does not group results. */
    readonly labels: PlatformAlertApiLabels
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
    /** How the alert splits its results into instances. */
    readonly grouping: GroupingApi
    /**
     * Time until which every instance's notifications are muted. Null when not muted. An instance's own snooze_until mutes one group, and the later of the two holds.
     * @nullable
     */
    readonly snooze_until: string | null
    /** Whether the alert's checks succeed. Holds for every instance, because a failed check names no group.
     *
     * * `ok` - OK
     * * `errored` - Errored
     * * `broken` - Broken */
    readonly check_status: PlatformAlertCheckStatusEnumApi
    /** New groups the last successful check could not track because the alert already held grouping.max_instances instances. 0 when every group fit. */
    readonly overflowed_groups: number
    /** Whether the last successful check cut its results before counting overflowed_groups. When true, more groups than overflowed_groups may be untracked. */
    readonly overflow_is_lower_bound: boolean
    /** Which stack evaluates and delivers the alert. Only an alert the platform owns can be edited here. The source product's own API edits the rest.
     *
     * * `source` - Source
     * * `platform` - Platform */
    readonly owner: PlatformAlertOwnerEnumApi
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

/**
 * Product whose data the alert evaluates. It cannot change after the create.
 */
export type LogsPlatformAlertConfigurationCreateApiSourceKind =
    (typeof LogsPlatformAlertConfigurationCreateApiSourceKind)[keyof typeof LogsPlatformAlertConfigurationCreateApiSourceKind]

export const LogsPlatformAlertConfigurationCreateApiSourceKind = {
    Logs: 'logs',
} as const

export type FilterLogicalOperatorApi = (typeof FilterLogicalOperatorApi)[keyof typeof FilterLogicalOperatorApi]

export const FilterLogicalOperatorApi = {
    And: 'AND',
    Or: 'OR',
} as const

export type PropertyOperatorApi = (typeof PropertyOperatorApi)[keyof typeof PropertyOperatorApi]

export const PropertyOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    StartsWith: 'starts_with',
    NotStartsWith: 'not_starts_with',
    EndsWith: 'ends_with',
    NotEndsWith: 'not_ends_with',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Gte: 'gte',
    Lt: 'lt',
    Lte: 'lte',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
    Between: 'between',
    NotBetween: 'not_between',
    Min: 'min',
    Max: 'max',
    In: 'in',
    NotIn: 'not_in',
    IsCleanedPathExact: 'is_cleaned_path_exact',
    IsCleanedPathNotExact: 'is_cleaned_path_not_exact',
    FlagEvaluatesTo: 'flag_evaluates_to',
    SemverEq: 'semver_eq',
    SemverNeq: 'semver_neq',
    SemverGt: 'semver_gt',
    SemverGte: 'semver_gte',
    SemverLt: 'semver_lt',
    SemverLte: 'semver_lte',
    SemverTilde: 'semver_tilde',
    SemverCaret: 'semver_caret',
    SemverWildcard: 'semver_wildcard',
    IcontainsMulti: 'icontains_multi',
    NotIcontainsMulti: 'not_icontains_multi',
} as const

export interface EventPropertyFilterApi {
    key: string
    label?: string | null
    operator?: PropertyOperatorApi | null
    /** Event properties */
    type?: 'event'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Person properties */
    type?: 'person'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PersonMetadataPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Top-level columns on the persons table (e.g. created_at), not properties JSON */
    type?: 'person_metadata'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type Key10Api = (typeof Key10Api)[keyof typeof Key10Api]

export const Key10Api = {
    TagName: 'tag_name',
    Text: 'text',
    Href: 'href',
    Selector: 'selector',
} as const

export interface ElementPropertyFilterApi {
    key: Key10Api
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'element'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface EventMetadataPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'event_metadata'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface SessionPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'session'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface CohortPropertyFilterApi {
    /** Set by the feature flag API when the cohort is deleted or does not exist. */
    cohort_deleted?: boolean | null
    /** Set by the feature flag API when the cohort does not exist, so it cannot be restored. */
    cohort_missing?: boolean | null
    cohort_name?: string | null
    key?: 'id'
    label?: string | null
    operator?: PropertyOperatorApi | null
    type?: 'cohort'
    value: number
}

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

export const DurationTypeApi = {
    Duration: 'duration',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
} as const

export interface RecordingPropertyFilterApi {
    key: DurationTypeApi | string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'recording'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface LogEntryPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'log_entry'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type GroupPropertyFilterApiGroupKeyNames = { [key: string]: string } | null

export interface GroupPropertyFilterApi {
    group_key_names?: GroupPropertyFilterApiGroupKeyNames
    group_type_index?: number | null
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'group'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FeaturePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Event property with "$feature/" prepended */
    type?: 'feature'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FlagPropertyFilterApi {
    /** The key should be the flag ID */
    key: string
    label?: string | null
    /** Only flag_evaluates_to operator is allowed for flag dependencies */
    operator?: 'flag_evaluates_to'
    /** Feature flag dependency */
    type?: 'flag'
    /** The value can be true, false, or a variant name */
    value: boolean | string
}

export interface HogQLPropertyFilterApi {
    key: string
    label?: string | null
    type?: 'hogql'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export const EmptyPropertyFilterApiValue = {
    type: 'empty',
} as const
export type EmptyPropertyFilterApi = typeof EmptyPropertyFilterApiValue

export interface DataWarehousePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface DataWarehousePersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse_person_property'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface ErrorTrackingIssueFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'error_tracking_issue'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type LogPropertyFilterTypeApi = (typeof LogPropertyFilterTypeApi)[keyof typeof LogPropertyFilterTypeApi]

export const LogPropertyFilterTypeApi = {
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
} as const

export interface LogPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type: LogPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface MetricPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'metric_attribute'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type SpanPropertyFilterTypeApi = (typeof SpanPropertyFilterTypeApi)[keyof typeof SpanPropertyFilterTypeApi]

export const SpanPropertyFilterTypeApi = {
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

export interface SpanPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type: SpanPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface RevenueAnalyticsPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'revenue_analytics'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface AccountCustomPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Customer analytics account custom property — the key is the property definition id */
    type?: 'account_custom_property'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface WorkflowVariablePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'workflow_variable'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type BehavioralEventSourceApi = (typeof BehavioralEventSourceApi)[keyof typeof BehavioralEventSourceApi]

export const BehavioralEventSourceApi = {
    Events: 'events',
    Actions: 'actions',
} as const

export type TimeUnitTypeApi = (typeof TimeUnitTypeApi)[keyof typeof TimeUnitTypeApi]

export const TimeUnitTypeApi = {
    Day: 'day',
    Week: 'week',
    Month: 'month',
    Year: 'year',
} as const

export type InlineBehavioralTypeApi = (typeof InlineBehavioralTypeApi)[keyof typeof InlineBehavioralTypeApi]

export const InlineBehavioralTypeApi = {
    PerformedEvent: 'performed_event',
    PerformedEventMultiple: 'performed_event_multiple',
} as const

export interface BehavioralPropertyFilterApi {
    /** Extra property filters the matching events must satisfy. Deliberately excludes nested behavioral/cohort filters and groups */
    event_filters?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | FeaturePropertyFilterApi
              | HogQLPropertyFilterApi
          )[]
        | null
    event_type: BehavioralEventSourceApi
    /** Absolute or relative (e.g. -30d) lower date bound — alternative to time_value/time_interval */
    explicit_datetime?: string | null
    explicit_datetime_to?: string | null
    /** Event name, or action id when event_type is 'actions' */
    key: string
    label?: string | null
    /** Match persons who did NOT satisfy the criterion. Not the same as a low count — zero-occurrence persons never match count operators */
    negation?: boolean | null
    /** Count comparison for performed_event_multiple, defaults to exact */
    operator?: PropertyOperatorApi | null
    /** Count threshold for performed_event_multiple */
    operator_value?: number | null
    time_interval?: TimeUnitTypeApi | null
    /** Relative time window size, paired with time_interval */
    time_value?: number | null
    /** Person performed (or didn't perform) an event in a time window. ClickHouse-only — not evaluable by flags or CDP */
    type?: 'behavioral'
    value: InlineBehavioralTypeApi
}

export interface PropertyGroupFilterValueApi {
    type: FilterLogicalOperatorApi
    values: (
        | PropertyGroupFilterValueApi
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | PersonMetadataPropertyFilterApi
        | ElementPropertyFilterApi
        | EventMetadataPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
        | RecordingPropertyFilterApi
        | LogEntryPropertyFilterApi
        | GroupPropertyFilterApi
        | FeaturePropertyFilterApi
        | FlagPropertyFilterApi
        | HogQLPropertyFilterApi
        | EmptyPropertyFilterApi
        | DataWarehousePropertyFilterApi
        | DataWarehousePersonPropertyFilterApi
        | ErrorTrackingIssueFilterApi
        | LogPropertyFilterApi
        | MetricPropertyFilterApi
        | SpanPropertyFilterApi
        | RevenueAnalyticsPropertyFilterApi
        | AccountCustomPropertyFilterApi
        | WorkflowVariablePropertyFilterApi
        | BehavioralPropertyFilterApi
    )[]
}

export interface PropertyGroupFilterApi {
    type: FilterLogicalOperatorApi
    values: PropertyGroupFilterValueApi[]
}

export type LogSeverityLevelApi = (typeof LogSeverityLevelApi)[keyof typeof LogSeverityLevelApi]

export const LogSeverityLevelApi = {
    Trace: 'trace',
    Debug: 'debug',
    Info: 'info',
    Warn: 'warn',
    Error: 'error',
    Fatal: 'fatal',
} as const

export interface LogsAlertFiltersApi {
    filterGroup?: PropertyGroupFilterApi | null
    serviceNames?: string[] | null
    severityLevels?: LogSeverityLevelApi[] | null
}

export type ThresholdOperatorApi = (typeof ThresholdOperatorApi)[keyof typeof ThresholdOperatorApi]

export const ThresholdOperatorApi = {
    Above: 'above',
    Below: 'below',
} as const

export type WindowMinutesEnumApi = (typeof WindowMinutesEnumApi)[keyof typeof WindowMinutesEnumApi]

export const WindowMinutesEnumApi = {
    Number5: 5,
    Number10: 10,
    Number15: 15,
    Number30: 30,
    Number60: 60,
} as const

export interface LogsPlatformAlertConditionApi {
    /**
     * Number of matching log entries in the window that breaches the threshold. Use 0 with the above operator to fire on any matching log.
     * @minimum 0
     * @maximum 2147483647
     */
    threshold_count: number
    /** Whether the alert fires when the count is above or below the threshold. */
    threshold_operator: ThresholdOperatorApi
    /** Time window in minutes over which logs are counted. */
    window_minutes: WindowMinutesEnumApi
}

export interface LogsPlatformAlertSourceConfigApi {
    /** The logs the alert counts: severityLevels, serviceNames, or a filterGroup of property filters. An enabled alert needs at least one. */
    filters: LogsAlertFiltersApi
    /** The bound the count is checked against. */
    condition: LogsPlatformAlertConditionApi
}

/**
 * The settings of a new alert. Every one but source_config has a default, which is stored.
 */
export interface LogsPlatformAlertConfigurationCreateApi {
    /** Product whose data the alert evaluates. It cannot change after the create. */
    source_kind: LogsPlatformAlertConfigurationCreateApiSourceKind
    /**
     * Human-readable name of the alert. Defaults to 'Untitled alert'.
     * @maxLength 255
     */
    name?: string
    /** Whether the alert is evaluated on schedule. Defaults to true. */
    enabled?: boolean
    /** Settings for a logs alert. The bound the alert is evaluated against is under condition. */
    source_config: LogsPlatformAlertSourceConfigApi
    /** How the alert splits its results into instances. Defaults to mode single. */
    grouping?: GroupingApi
    /** Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. Defaults to null. */
    schedule_restriction?: AlertScheduleRestrictionApi | null
    /**
     * Number of recent checks considered when deciding to fire. Defaults to 1.
     * @minimum 1
     * @maximum 10
     */
    evaluation_periods?: number
    /**
     * Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.
     * @minimum 1
     * @maximum 10
     */
    datapoints_to_alarm?: number
    /**
     * Minimum minutes between notifications for the same alert. Defaults to 0.
     * @minimum 0
     * @maximum 2147483647
     */
    cooldown_minutes?: number
}

export type PlatformAlertConfigurationCreateApi = LogsPlatformAlertConfigurationCreateApi

/**
 * Product whose data the alert evaluates. It cannot change, so it must match the stored value.
 */
export type InsightPlatformAlertConfigurationEditApiSourceKind =
    (typeof InsightPlatformAlertConfigurationEditApiSourceKind)[keyof typeof InsightPlatformAlertConfigurationEditApiSourceKind]

export const InsightPlatformAlertConfigurationEditApiSourceKind = {
    Insight: 'insight',
} as const

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

export type AlertConditionTypeApi = (typeof AlertConditionTypeApi)[keyof typeof AlertConditionTypeApi]

export const AlertConditionTypeApi = {
    AbsoluteValue: 'absolute_value',
    RelativeIncrease: 'relative_increase',
    RelativeDecrease: 'relative_decrease',
} as const

export interface AlertConditionApi {
    type: AlertConditionTypeApi
}

export interface InsightPlatformAlertConditionApi {
    /** The bounds the insight's value is checked against, absolute or as a percentage change. */
    threshold: InsightThresholdApi | null
    /** How the value is compared: as it is, or as an increase or decrease from the previous interval. */
    comparison: AlertConditionApi
    /**
     * Always null. The platform owns threshold alerts only, so no detector applies.
     * @nullable
     */
    detector?: null
}

export interface InsightPlatformAlertSourceConfigApi {
    /** The insight the alert checks. It cannot change through this API. */
    insight_id: number
    /** The bound the insight's value is checked against. */
    condition: InsightPlatformAlertConditionApi
}

/**
 * The settings an edit can change. Each source kind subclasses it with a typed `source_config`.
 */
export interface InsightPlatformAlertConfigurationEditApi {
    /** Product whose data the alert evaluates. It cannot change, so it must match the stored value. */
    source_kind: InsightPlatformAlertConfigurationEditApiSourceKind
    /**
     * Human-readable name of the alert.
     * @maxLength 255
     */
    name: string
    /** Whether the alert is evaluated on schedule. */
    enabled: boolean
    /** Settings for a insight alert. The bound the alert is evaluated against is under condition. */
    source_config: InsightPlatformAlertSourceConfigApi
    /** How the alert splits its results into instances. */
    grouping: GroupingApi
    /** Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. */
    schedule_restriction: AlertScheduleRestrictionApi | null
    /**
     * Number of recent checks considered when deciding to fire.
     * @minimum 1
     * @maximum 10
     */
    evaluation_periods: number
    /**
     * Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.
     * @minimum 1
     * @maximum 10
     */
    datapoints_to_alarm: number
    /**
     * Minimum minutes between notifications for the same alert.
     * @minimum 0
     * @maximum 2147483647
     */
    cooldown_minutes: number
}

/**
 * Product whose data the alert evaluates. It cannot change, so it must match the stored value.
 */
export type LogsPlatformAlertConfigurationEditApiSourceKind =
    (typeof LogsPlatformAlertConfigurationEditApiSourceKind)[keyof typeof LogsPlatformAlertConfigurationEditApiSourceKind]

export const LogsPlatformAlertConfigurationEditApiSourceKind = {
    Logs: 'logs',
} as const

/**
 * The settings an edit can change. Each source kind subclasses it with a typed `source_config`.
 */
export interface LogsPlatformAlertConfigurationEditApi {
    /** Product whose data the alert evaluates. It cannot change, so it must match the stored value. */
    source_kind: LogsPlatformAlertConfigurationEditApiSourceKind
    /**
     * Human-readable name of the alert.
     * @maxLength 255
     */
    name: string
    /** Whether the alert is evaluated on schedule. */
    enabled: boolean
    /** Settings for a logs alert. The bound the alert is evaluated against is under condition. */
    source_config: LogsPlatformAlertSourceConfigApi
    /** How the alert splits its results into instances. */
    grouping: GroupingApi
    /** Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. */
    schedule_restriction: AlertScheduleRestrictionApi | null
    /**
     * Number of recent checks considered when deciding to fire.
     * @minimum 1
     * @maximum 10
     */
    evaluation_periods: number
    /**
     * Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.
     * @minimum 1
     * @maximum 10
     */
    datapoints_to_alarm: number
    /**
     * Minimum minutes between notifications for the same alert.
     * @minimum 0
     * @maximum 2147483647
     */
    cooldown_minutes: number
}

export type PlatformAlertConfigurationEditApi =
    | InsightPlatformAlertConfigurationEditApi
    | LogsPlatformAlertConfigurationEditApi

/**
 * Product whose data the alert evaluates. It cannot change, so it must match the stored value.
 */
export type PatchedInsightPlatformAlertConfigurationEditApiSourceKind =
    (typeof PatchedInsightPlatformAlertConfigurationEditApiSourceKind)[keyof typeof PatchedInsightPlatformAlertConfigurationEditApiSourceKind]

export const PatchedInsightPlatformAlertConfigurationEditApiSourceKind = {
    Insight: 'insight',
} as const

/**
 * The settings an edit can change. Each source kind subclasses it with a typed `source_config`.
 */
export interface PatchedInsightPlatformAlertConfigurationEditApi {
    /** Product whose data the alert evaluates. It cannot change, so it must match the stored value. */
    source_kind: PatchedInsightPlatformAlertConfigurationEditApiSourceKind
    /**
     * Human-readable name of the alert.
     * @maxLength 255
     */
    name?: string
    /** Whether the alert is evaluated on schedule. */
    enabled?: boolean
    /** Settings for a insight alert. The bound the alert is evaluated against is under condition. */
    source_config?: InsightPlatformAlertSourceConfigApi
    /** How the alert splits its results into instances. */
    grouping?: GroupingApi
    /** Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. */
    schedule_restriction?: AlertScheduleRestrictionApi | null
    /**
     * Number of recent checks considered when deciding to fire.
     * @minimum 1
     * @maximum 10
     */
    evaluation_periods?: number
    /**
     * Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.
     * @minimum 1
     * @maximum 10
     */
    datapoints_to_alarm?: number
    /**
     * Minimum minutes between notifications for the same alert.
     * @minimum 0
     * @maximum 2147483647
     */
    cooldown_minutes?: number
}

/**
 * Product whose data the alert evaluates. It cannot change, so it must match the stored value.
 */
export type PatchedLogsPlatformAlertConfigurationEditApiSourceKind =
    (typeof PatchedLogsPlatformAlertConfigurationEditApiSourceKind)[keyof typeof PatchedLogsPlatformAlertConfigurationEditApiSourceKind]

export const PatchedLogsPlatformAlertConfigurationEditApiSourceKind = {
    Logs: 'logs',
} as const

/**
 * The settings an edit can change. Each source kind subclasses it with a typed `source_config`.
 */
export interface PatchedLogsPlatformAlertConfigurationEditApi {
    /** Product whose data the alert evaluates. It cannot change, so it must match the stored value. */
    source_kind: PatchedLogsPlatformAlertConfigurationEditApiSourceKind
    /**
     * Human-readable name of the alert.
     * @maxLength 255
     */
    name?: string
    /** Whether the alert is evaluated on schedule. */
    enabled?: boolean
    /** Settings for a logs alert. The bound the alert is evaluated against is under condition. */
    source_config?: LogsPlatformAlertSourceConfigApi
    /** How the alert splits its results into instances. */
    grouping?: GroupingApi
    /** Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. */
    schedule_restriction?: AlertScheduleRestrictionApi | null
    /**
     * Number of recent checks considered when deciding to fire.
     * @minimum 1
     * @maximum 10
     */
    evaluation_periods?: number
    /**
     * Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.
     * @minimum 1
     * @maximum 10
     */
    datapoints_to_alarm?: number
    /**
     * Minimum minutes between notifications for the same alert.
     * @minimum 0
     * @maximum 2147483647
     */
    cooldown_minutes?: number
}

export type PatchedPlatformAlertConfigurationEditApi =
    | PatchedInsightPlatformAlertConfigurationEditApi
    | PatchedLogsPlatformAlertConfigurationEditApi

export interface PlatformAlertGroupSnoozeApi {
    /**
     * Key of the group to snooze, as the grouping_key of one of the alert's instances.
     * @maxLength 255
     */
    grouping_key: string
    /**
     * Time until which this group's notifications are muted. Must be in the future and at most 30 days away. Null clears the group's snooze. The group keeps being checked, and its firing stays open.
     * @nullable
     */
    snooze_until: string | null
}

export type PlatformAlertsListParams = {
    /**
     * Only the alert copied from, or created with, this source configuration, such as a logs alert's id.
     */
    legacy_configuration_id?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
