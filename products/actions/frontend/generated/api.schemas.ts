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
 * * `event` - event
 * `event_metadata` - event_metadata
 * `feature` - feature
 * `person` - person
 * `cohort` - cohort
 * `element` - element
 * `static-cohort` - static-cohort
 * `dynamic-cohort` - dynamic-cohort
 * `precalculated-cohort` - precalculated-cohort
 * `group` - group
 * `recording` - recording
 * `log_entry` - log_entry
 * `behavioral` - behavioral
 * `session` - session
 * `hogql` - hogql
 * `data_warehouse` - data_warehouse
 * `data_warehouse_person_property` - data_warehouse_person_property
 * `error_tracking_issue` - error_tracking_issue
 * `log` - log
 * `log_attribute` - log_attribute
 * `log_resource_attribute` - log_resource_attribute
 * `revenue_analytics` - revenue_analytics
 * `flag` - flag
 * `workflow_variable` - workflow_variable
 */
export type Type19aEnumApi = (typeof Type19aEnumApi)[keyof typeof Type19aEnumApi]

export const Type19aEnumApi = {
    Event: 'event',
    EventMetadata: 'event_metadata',
    Feature: 'feature',
    Person: 'person',
    Cohort: 'cohort',
    Element: 'element',
    StaticCohort: 'static-cohort',
    DynamicCohort: 'dynamic-cohort',
    PrecalculatedCohort: 'precalculated-cohort',
    Group: 'group',
    Recording: 'recording',
    LogEntry: 'log_entry',
    Behavioral: 'behavioral',
    Session: 'session',
    Hogql: 'hogql',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
    ErrorTrackingIssue: 'error_tracking_issue',
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
    RevenueAnalytics: 'revenue_analytics',
    Flag: 'flag',
    WorkflowVariable: 'workflow_variable',
} as const

/**
 * * `exact` - exact
 * `is_not` - is_not
 * `icontains` - icontains
 * `not_icontains` - not_icontains
 * `regex` - regex
 * `not_regex` - not_regex
 */
export type StringPropertyFilterOperatorEnumApi =
    (typeof StringPropertyFilterOperatorEnumApi)[keyof typeof StringPropertyFilterOperatorEnumApi]

export const StringPropertyFilterOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
} as const

/**
 * Matches string values with text-oriented operators.
 */
export interface StringPropertyFilterApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url`. */
    key: string
    /** Property type (event, person, session, etc.).

* `event` - event
* `event_metadata` - event_metadata
* `feature` - feature
* `person` - person
* `cohort` - cohort
* `element` - element
* `static-cohort` - static-cohort
* `dynamic-cohort` - dynamic-cohort
* `precalculated-cohort` - precalculated-cohort
* `group` - group
* `recording` - recording
* `log_entry` - log_entry
* `behavioral` - behavioral
* `session` - session
* `hogql` - hogql
* `data_warehouse` - data_warehouse
* `data_warehouse_person_property` - data_warehouse_person_property
* `error_tracking_issue` - error_tracking_issue
* `log` - log
* `log_attribute` - log_attribute
* `log_resource_attribute` - log_resource_attribute
* `revenue_analytics` - revenue_analytics
* `flag` - flag
* `workflow_variable` - workflow_variable */
    type?: Type19aEnumApi
    /** String value to match against. */
    value: string
    /** String comparison operator.

* `exact` - exact
* `is_not` - is_not
* `icontains` - icontains
* `not_icontains` - not_icontains
* `regex` - regex
* `not_regex` - not_regex */
    operator?: StringPropertyFilterOperatorEnumApi
}

/**
 * * `exact` - exact
 * `is_not` - is_not
 * `gt` - gt
 * `lt` - lt
 * `gte` - gte
 * `lte` - lte
 */
export type NumericPropertyFilterOperatorEnumApi =
    (typeof NumericPropertyFilterOperatorEnumApi)[keyof typeof NumericPropertyFilterOperatorEnumApi]

export const NumericPropertyFilterOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Gt: 'gt',
    Lt: 'lt',
    Gte: 'gte',
    Lte: 'lte',
} as const

/**
 * Matches numeric values with comparison operators.
 */
export interface NumericPropertyFilterApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url`. */
    key: string
    /** Property type (event, person, session, etc.).

* `event` - event
* `event_metadata` - event_metadata
* `feature` - feature
* `person` - person
* `cohort` - cohort
* `element` - element
* `static-cohort` - static-cohort
* `dynamic-cohort` - dynamic-cohort
* `precalculated-cohort` - precalculated-cohort
* `group` - group
* `recording` - recording
* `log_entry` - log_entry
* `behavioral` - behavioral
* `session` - session
* `hogql` - hogql
* `data_warehouse` - data_warehouse
* `data_warehouse_person_property` - data_warehouse_person_property
* `error_tracking_issue` - error_tracking_issue
* `log` - log
* `log_attribute` - log_attribute
* `log_resource_attribute` - log_resource_attribute
* `revenue_analytics` - revenue_analytics
* `flag` - flag
* `workflow_variable` - workflow_variable */
    type?: Type19aEnumApi
    /** Numeric value to compare against. */
    value: number
    /** Numeric comparison operator.

* `exact` - exact
* `is_not` - is_not
* `gt` - gt
* `lt` - lt
* `gte` - gte
* `lte` - lte */
    operator?: NumericPropertyFilterOperatorEnumApi
}

/**
 * * `exact` - exact
 * `is_not` - is_not
 * `in` - in
 * `not_in` - not_in
 */
export type ArrayPropertyFilterOperatorEnumApi =
    (typeof ArrayPropertyFilterOperatorEnumApi)[keyof typeof ArrayPropertyFilterOperatorEnumApi]

export const ArrayPropertyFilterOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    In: 'in',
    NotIn: 'not_in',
} as const

/**
 * Matches against a list of values (OR semantics for exact/is_not, set membership for in/not_in).
 */
export interface ArrayPropertyFilterApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url`. */
    key: string
    /** Property type (event, person, session, etc.).

* `event` - event
* `event_metadata` - event_metadata
* `feature` - feature
* `person` - person
* `cohort` - cohort
* `element` - element
* `static-cohort` - static-cohort
* `dynamic-cohort` - dynamic-cohort
* `precalculated-cohort` - precalculated-cohort
* `group` - group
* `recording` - recording
* `log_entry` - log_entry
* `behavioral` - behavioral
* `session` - session
* `hogql` - hogql
* `data_warehouse` - data_warehouse
* `data_warehouse_person_property` - data_warehouse_person_property
* `error_tracking_issue` - error_tracking_issue
* `log` - log
* `log_attribute` - log_attribute
* `log_resource_attribute` - log_resource_attribute
* `revenue_analytics` - revenue_analytics
* `flag` - flag
* `workflow_variable` - workflow_variable */
    type?: Type19aEnumApi
    /** List of values to match. For example `["test@example.com", "ok@example.com"]`. */
    value: string[]
    /** Array comparison operator.

* `exact` - exact
* `is_not` - is_not
* `in` - in
* `not_in` - not_in */
    operator?: ArrayPropertyFilterOperatorEnumApi
}

/**
 * * `is_date_exact` - is_date_exact
 * `is_date_before` - is_date_before
 * `is_date_after` - is_date_after
 */
export type DatePropertyFilterOperatorEnumApi =
    (typeof DatePropertyFilterOperatorEnumApi)[keyof typeof DatePropertyFilterOperatorEnumApi]

export const DatePropertyFilterOperatorEnumApi = {
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
} as const

/**
 * Matches date/datetime values with date-specific operators.
 */
export interface DatePropertyFilterApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url`. */
    key: string
    /** Property type (event, person, session, etc.).

* `event` - event
* `event_metadata` - event_metadata
* `feature` - feature
* `person` - person
* `cohort` - cohort
* `element` - element
* `static-cohort` - static-cohort
* `dynamic-cohort` - dynamic-cohort
* `precalculated-cohort` - precalculated-cohort
* `group` - group
* `recording` - recording
* `log_entry` - log_entry
* `behavioral` - behavioral
* `session` - session
* `hogql` - hogql
* `data_warehouse` - data_warehouse
* `data_warehouse_person_property` - data_warehouse_person_property
* `error_tracking_issue` - error_tracking_issue
* `log` - log
* `log_attribute` - log_attribute
* `log_resource_attribute` - log_resource_attribute
* `revenue_analytics` - revenue_analytics
* `flag` - flag
* `workflow_variable` - workflow_variable */
    type?: Type19aEnumApi
    /** Date or datetime string in ISO 8601 format (e.g. '2024-01-15' or '2024-01-15T10:30:00Z'). */
    value: string
    /** Date comparison operator.

* `is_date_exact` - is_date_exact
* `is_date_before` - is_date_before
* `is_date_after` - is_date_after */
    operator?: DatePropertyFilterOperatorEnumApi
}

/**
 * * `is_set` - is_set
 * `is_not_set` - is_not_set
 */
export type Operator3e6EnumApi = (typeof Operator3e6EnumApi)[keyof typeof Operator3e6EnumApi]

export const Operator3e6EnumApi = {
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
} as const

/**
 * Checks whether a property is set or not, without comparing values.
 */
export interface ExistencePropertyFilterApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url`. */
    key: string
    /** Property type (event, person, session, etc.).

* `event` - event
* `event_metadata` - event_metadata
* `feature` - feature
* `person` - person
* `cohort` - cohort
* `element` - element
* `static-cohort` - static-cohort
* `dynamic-cohort` - dynamic-cohort
* `precalculated-cohort` - precalculated-cohort
* `group` - group
* `recording` - recording
* `log_entry` - log_entry
* `behavioral` - behavioral
* `session` - session
* `hogql` - hogql
* `data_warehouse` - data_warehouse
* `data_warehouse_person_property` - data_warehouse_person_property
* `error_tracking_issue` - error_tracking_issue
* `log` - log
* `log_attribute` - log_attribute
* `log_resource_attribute` - log_resource_attribute
* `revenue_analytics` - revenue_analytics
* `flag` - flag
* `workflow_variable` - workflow_variable */
    type?: Type19aEnumApi
    /** Existence check operator.

* `is_set` - is_set
* `is_not_set` - is_not_set */
    operator: Operator3e6EnumApi
}

export type ActionStepPropertyFilterApi =
    | StringPropertyFilterApi
    | NumericPropertyFilterApi
    | ArrayPropertyFilterApi
    | DatePropertyFilterApi
    | ExistencePropertyFilterApi

/**
 * * `contains` - contains
 * `regex` - regex
 * `exact` - exact
 */
export type UrlMatchingEnumApi = (typeof UrlMatchingEnumApi)[keyof typeof UrlMatchingEnumApi]

export const UrlMatchingEnumApi = {
    Contains: 'contains',
    Regex: 'regex',
    Exact: 'exact',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

export interface ActionStepJSONApi {
    /**
     * Event name to match (e.g. '$pageview', '$autocapture', or a custom event name).
     * @nullable
     */
    event?: string | null
    /**
     * Event or person property filters. Each item should have 'key' (string), 'value' (string, number, boolean, or array), optional 'operator' (exact, is_not, is_set, is_not_set, icontains, not_icontains, regex, not_regex, gt, gte, lt, lte), and optional 'type' (event, person).
     * @nullable
     */
    properties?: ActionStepPropertyFilterApi[] | null
    /**
     * CSS selector to match the target element (e.g. 'div > button.cta').
     * @nullable
     */
    selector?: string | null
    /** @nullable */
    readonly selector_regex: string | null
    /**
     * HTML tag name to match (e.g. "button", "a", "input").
     * @nullable
     */
    tag_name?: string | null
    /**
     * Element text content to match.
     * @nullable
     */
    text?: string | null
    /** How to match the text value. Defaults to exact.

* `contains` - contains
* `regex` - regex
* `exact` - exact */
    text_matching?: UrlMatchingEnumApi | NullEnumApi | null
    /**
     * Link href attribute to match.
     * @nullable
     */
    href?: string | null
    /** How to match the href value. Defaults to exact.

* `contains` - contains
* `regex` - regex
* `exact` - exact */
    href_matching?: UrlMatchingEnumApi | NullEnumApi | null
    /**
     * Page URL to match.
     * @nullable
     */
    url?: string | null
    /** How to match the URL value. Defaults to contains.

* `contains` - contains
* `regex` - regex
* `exact` - exact */
    url_matching?: UrlMatchingEnumApi | NullEnumApi | null
}

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

/**
 * Serializer mixin that handles tags for objects.
 */
export interface ActionApi {
    readonly id: number
    /**
     * Name of the action (must be unique within the project).
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Human-readable description of what this action represents. */
    description?: string
    tags?: unknown[]
    /** Whether to post a notification to Slack when this action is triggered. */
    post_to_slack?: boolean
    /**
     * Custom Slack message format. Supports templates with event properties.
     * @maxLength 1200
     */
    slack_message_format?: string
    /** Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together. */
    steps?: ActionStepJSONApi[]
    readonly created_at: string
    readonly created_by: UserBasicApi
    deleted?: boolean
    readonly is_calculating: boolean
    last_calculated_at?: string
    readonly team_id: number
    readonly is_action: boolean
    /** @nullable */
    readonly bytecode_error: string | null
    /**
     * ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.
     * @nullable
     */
    pinned_at?: string | null
    /** @nullable */
    readonly creation_context: string | null
    _create_in_folder?: string
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedActionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ActionApi[]
}

/**
 * Serializer mixin that handles tags for objects.
 */
export interface PatchedActionApi {
    readonly id?: number
    /**
     * Name of the action (must be unique within the project).
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Human-readable description of what this action represents. */
    description?: string
    tags?: unknown[]
    /** Whether to post a notification to Slack when this action is triggered. */
    post_to_slack?: boolean
    /**
     * Custom Slack message format. Supports templates with event properties.
     * @maxLength 1200
     */
    slack_message_format?: string
    /** Action steps defining trigger conditions. Each step matches events by name, properties, URL, or element attributes. Multiple steps are OR-ed together. */
    steps?: ActionStepJSONApi[]
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    deleted?: boolean
    readonly is_calculating?: boolean
    last_calculated_at?: string
    readonly team_id?: number
    readonly is_action?: boolean
    /** @nullable */
    readonly bytecode_error?: string | null
    /**
     * ISO 8601 timestamp when the action was pinned, or null if not pinned. Set any value to pin, null to unpin.
     * @nullable
     */
    pinned_at?: string | null
    /** @nullable */
    readonly creation_context?: string | null
    _create_in_folder?: string
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
}

export type ActionsListParams = {
    format?: ActionsListFormat
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ActionsListFormat = (typeof ActionsListFormat)[keyof typeof ActionsListFormat]

export const ActionsListFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type ActionsCreateParams = {
    format?: ActionsCreateFormat
}

export type ActionsCreateFormat = (typeof ActionsCreateFormat)[keyof typeof ActionsCreateFormat]

export const ActionsCreateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type ActionsRetrieveParams = {
    format?: ActionsRetrieveFormat
}

export type ActionsRetrieveFormat = (typeof ActionsRetrieveFormat)[keyof typeof ActionsRetrieveFormat]

export const ActionsRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type ActionsUpdateParams = {
    format?: ActionsUpdateFormat
}

export type ActionsUpdateFormat = (typeof ActionsUpdateFormat)[keyof typeof ActionsUpdateFormat]

export const ActionsUpdateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type ActionsPartialUpdateParams = {
    format?: ActionsPartialUpdateFormat
}

export type ActionsPartialUpdateFormat = (typeof ActionsPartialUpdateFormat)[keyof typeof ActionsPartialUpdateFormat]

export const ActionsPartialUpdateFormat = {
    Csv: 'csv',
    Json: 'json',
} as const

export type ActionsDestroyParams = {
    format?: ActionsDestroyFormat
}

export type ActionsDestroyFormat = (typeof ActionsDestroyFormat)[keyof typeof ActionsDestroyFormat]

export const ActionsDestroyFormat = {
    Csv: 'csv',
    Json: 'json',
} as const
