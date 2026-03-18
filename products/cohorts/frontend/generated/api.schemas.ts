/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type PropertyGroupOperatorApi = (typeof PropertyGroupOperatorApi)[keyof typeof PropertyGroupOperatorApi]

export const PropertyGroupOperatorApi = {
    And: 'AND',
    Or: 'OR',
} as const

export type BehavioralFilterApiType = (typeof BehavioralFilterApiType)[keyof typeof BehavioralFilterApiType]

export const BehavioralFilterApiType = {
    Behavioral: 'behavioral',
} as const

export type EventPropFilterTypeEnumApi = (typeof EventPropFilterTypeEnumApi)[keyof typeof EventPropFilterTypeEnumApi]

export const EventPropFilterTypeEnumApi = {
    Event: 'event',
    Element: 'element',
} as const

export interface EventPropFilterApi {
    type: EventPropFilterTypeEnumApi
    key: string
    value: unknown
    /** @nullable */
    operator?: string | null
}

export type HogQLFilterApiType = (typeof HogQLFilterApiType)[keyof typeof HogQLFilterApiType]

export const HogQLFilterApiType = {
    Hogql: 'hogql',
} as const

export interface HogQLFilterApi {
    type: HogQLFilterApiType
    key: string
    value?: unknown | null
}

export interface BehavioralFilterApi {
    /** @nullable */
    bytecode?: unknown[] | null
    /** @nullable */
    bytecode_error?: string | null
    /** @nullable */
    conditionHash?: string | null
    type: BehavioralFilterApiType
    key: string | number
    value: string
    event_type: string
    /** @nullable */
    time_value?: number | null
    /** @nullable */
    time_interval?: string | null
    negation?: boolean
    /** @nullable */
    operator?: string | null
    /** @nullable */
    operator_value?: number | null
    /** @nullable */
    seq_time_interval?: string | null
    /** @nullable */
    seq_time_value?: number | null
    seq_event?: string | number | null
    /** @nullable */
    seq_event_type?: string | null
    /** @nullable */
    total_periods?: number | null
    /** @nullable */
    min_periods?: number | null
    /** @nullable */
    event_filters?: (EventPropFilterApi | HogQLFilterApi)[] | null
    /** @nullable */
    explicit_datetime?: string | null
}

export type CohortFilterApiType = (typeof CohortFilterApiType)[keyof typeof CohortFilterApiType]

export const CohortFilterApiType = {
    Cohort: 'cohort',
} as const

export type CohortFilterApiKey = (typeof CohortFilterApiKey)[keyof typeof CohortFilterApiKey]

export const CohortFilterApiKey = {
    Id: 'id',
} as const

export interface CohortFilterApi {
    /** @nullable */
    bytecode?: unknown[] | null
    /** @nullable */
    bytecode_error?: string | null
    /** @nullable */
    conditionHash?: string | null
    type: CohortFilterApiType
    key: CohortFilterApiKey
    value: number
    negation?: boolean
}

export type PersonFilterApiType = (typeof PersonFilterApiType)[keyof typeof PersonFilterApiType]

export const PersonFilterApiType = {
    Person: 'person',
} as const

export interface PersonFilterApi {
    /** @nullable */
    bytecode?: unknown[] | null
    /** @nullable */
    bytecode_error?: string | null
    /** @nullable */
    conditionHash?: string | null
    type: PersonFilterApiType
    key: string
    /** @nullable */
    operator?: string | null
    value?: unknown | null
    negation?: boolean
}

/**
 * AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.
 */
export interface CohortFilterGroupApi {
    type: PropertyGroupOperatorApi
    values: (BehavioralFilterApi | CohortFilterApi | PersonFilterApi | CohortFilterGroupApi)[]
}

export interface CohortFiltersApi {
    properties: CohortFilterGroupApi
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

/**
 * * `static` - static
 * `person_property` - person_property
 * `behavioral` - behavioral
 * `realtime` - realtime
 * `analytical` - analytical
 */
export type CohortTypeEnumApi = (typeof CohortTypeEnumApi)[keyof typeof CohortTypeEnumApi]

export const CohortTypeEnumApi = {
    Static: 'static',
    PersonProperty: 'person_property',
    Behavioral: 'behavioral',
    Realtime: 'realtime',
    Analytical: 'analytical',
} as const

export interface CohortApi {
    readonly id: number
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** @maxLength 1000 */
    description?: string
    groups?: unknown
    deleted?: boolean
    filters?: CohortFiltersApi | null
    query?: unknown | null
    /** @nullable */
    readonly version: number | null
    /** @nullable */
    readonly pending_version: number | null
    readonly is_calculating: boolean
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly created_at: string | null
    /** @nullable */
    readonly last_calculation: string | null
    readonly errors_calculating: number
    /** @nullable */
    readonly last_error_message: string | null
    /** @nullable */
    readonly count: number | null
    is_static?: boolean
    /** Type of cohort based on filter complexity

* `static` - static
* `person_property` - person_property
* `behavioral` - behavioral
* `realtime` - realtime
* `analytical` - analytical */
    cohort_type?: CohortTypeEnumApi | BlankEnumApi | NullEnumApi | null
    readonly experiment_set: readonly number[]
    _create_in_folder?: string
    _create_static_person_ids?: string[]
}

export interface PaginatedCohortListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CohortApi[]
}

export interface PatchedCohortApi {
    readonly id?: number
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** @maxLength 1000 */
    description?: string
    groups?: unknown
    deleted?: boolean
    filters?: CohortFiltersApi | null
    query?: unknown | null
    /** @nullable */
    readonly version?: number | null
    /** @nullable */
    readonly pending_version?: number | null
    readonly is_calculating?: boolean
    readonly created_by?: UserBasicApi
    /** @nullable */
    readonly created_at?: string | null
    /** @nullable */
    readonly last_calculation?: string | null
    readonly errors_calculating?: number
    /** @nullable */
    readonly last_error_message?: string | null
    /** @nullable */
    readonly count?: number | null
    is_static?: boolean
    /** Type of cohort based on filter complexity

* `static` - static
* `person_property` - person_property
* `behavioral` - behavioral
* `realtime` - realtime
* `analytical` - analytical */
    cohort_type?: CohortTypeEnumApi | BlankEnumApi | NullEnumApi | null
    readonly experiment_set?: readonly number[]
    _create_in_folder?: string
    _create_static_person_ids?: string[]
}

export interface PatchedAddPersonsToStaticCohortRequestApi {
    /** List of person UUIDs to add to the cohort */
    person_ids?: string[]
}

export interface PatchedRemovePersonRequestApi {
    /** Person UUID to remove from the cohort */
    person_id?: string
}

export type CohortsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CohortsPersonsRetrieveParams = {
    format?: CohortsPersonsRetrieveFormat
}

export type CohortsPersonsRetrieveFormat =
    (typeof CohortsPersonsRetrieveFormat)[keyof typeof CohortsPersonsRetrieveFormat]

export const CohortsPersonsRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const
