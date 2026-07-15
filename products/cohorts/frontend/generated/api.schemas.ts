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

export type EventPropFilterTypeEnumApi = (typeof EventPropFilterTypeEnumApi)[keyof typeof EventPropFilterTypeEnumApi]

export const EventPropFilterTypeEnumApi = {
    Event: 'event',
    Element: 'element',
} as const

export interface EventPropFilterApi {
    type: EventPropFilterTypeEnumApi
    key: string
    value: unknown
    operator?: string | null
}

export interface HogQLFilterApi {
    type: 'hogql'
    key: string
    value?: unknown
}

export interface BehavioralFilterApi {
    bytecode?: unknown[] | null
    bytecode_error?: string | null
    conditionHash?: string | null
    type: 'behavioral'
    key: string | number
    value: string
    event_type: string
    time_value?: number | null
    time_interval?: string | null
    negation?: boolean
    operator?: string | null
    operator_value?: number | null
    seq_time_interval?: string | null
    seq_time_value?: number | null
    seq_event?: string | number | null
    seq_event_type?: string | null
    total_periods?: number | null
    min_periods?: number | null
    event_filters?: (EventPropFilterApi | HogQLFilterApi)[] | null
    explicit_datetime?: string | null
    explicit_datetime_to?: string | null
}

export interface CohortFilterApi {
    bytecode?: unknown[] | null
    bytecode_error?: string | null
    conditionHash?: string | null
    type: 'cohort'
    key: 'id'
    value: number
    negation?: boolean
}

export interface PersonFilterApi {
    operator?: string | null
    value?: unknown
    bytecode?: unknown[] | null
    bytecode_error?: string | null
    conditionHash?: string | null
    type: 'person'
    key: string
    negation?: boolean
}

/**
 * Filter on a top-level persons-table column (e.g. created_at) rather than the
 * properties JSON. The matching key must be one of PERSON_METADATA_FIELDS.
 */
export interface PersonMetadataFilterApi {
    operator?: string | null
    value?: unknown
    bytecode?: unknown[] | null
    bytecode_error?: string | null
    conditionHash?: string | null
    type: 'person_metadata'
    key: string
    negation?: boolean
}

/**
 * AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.
 */
export interface CohortFilterGroupApi {
    type: PropertyGroupOperatorApi
    values: (BehavioralFilterApi | CohortFilterApi | PersonFilterApi | PersonMetadataFilterApi | CohortFilterGroupApi)[]
}

export interface CohortFiltersApi {
    properties: CohortFilterGroupApi
}

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
 * * `static` - static
 * * `person_property` - person_property
 * * `behavioral` - behavioral
 * * `realtime` - realtime
 * * `analytical` - analytical
 */
export type CohortTypeEnumApi = (typeof CohortTypeEnumApi)[keyof typeof CohortTypeEnumApi]

export const CohortTypeEnumApi = {
    Static: 'static',
    PersonProperty: 'person_property',
    Behavioral: 'behavioral',
    Realtime: 'realtime',
    Analytical: 'analytical',
} as const

export type SearchMatchTypeEnumApi = (typeof SearchMatchTypeEnumApi)[keyof typeof SearchMatchTypeEnumApi]

export const SearchMatchTypeEnumApi = {
    Exact: 'exact',
    Similar: 'similar',
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
    query?: unknown
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
    /** @nullable */
    readonly last_backfill_person_properties_at: string | null
    readonly errors_calculating: number
    /** @nullable */
    readonly last_error_message: string | null
    /** @nullable */
    readonly count: number | null
    is_static?: boolean
    /** Type of cohort based on filter complexity
     *
     * * `static` - static
     * * `person_property` - person_property
     * * `behavioral` - behavioral
     * * `realtime` - realtime
     * * `analytical` - analytical */
    cohort_type?: CohortTypeEnumApi | BlankEnumApi | null
    readonly experiment_set: readonly number[]
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`. */
    readonly search_match_type: SearchMatchTypeEnumApi | null
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
    query?: unknown
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
    /** @nullable */
    readonly last_backfill_person_properties_at?: string | null
    readonly errors_calculating?: number
    /** @nullable */
    readonly last_error_message?: string | null
    /** @nullable */
    readonly count?: number | null
    is_static?: boolean
    /** Type of cohort based on filter complexity
     *
     * * `static` - static
     * * `person_property` - person_property
     * * `behavioral` - behavioral
     * * `realtime` - realtime
     * * `analytical` - analytical */
    cohort_type?: CohortTypeEnumApi | BlankEnumApi | null
    readonly experiment_set?: readonly number[]
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`. */
    readonly search_match_type?: SearchMatchTypeEnumApi | null
    _create_in_folder?: string
    _create_static_person_ids?: string[]
}

export interface PatchedAddPersonsToStaticCohortRequestApi {
    /** List of person UUIDs to add to the cohort */
    person_ids?: string[]
}

/**
 * * `person` - person
 */
export type CohortPersonResultTypeEnumApi =
    (typeof CohortPersonResultTypeEnumApi)[keyof typeof CohortPersonResultTypeEnumApi]

export const CohortPersonResultTypeEnumApi = {
    Person: 'person',
} as const

export type CohortPersonResultApiProperties = { [key: string]: unknown }

export type CohortPersonResultApiMatchedRecordingsItem = { [key: string]: unknown }

export interface CohortPersonResultApi {
    id: string
    uuid: string
    type: CohortPersonResultTypeEnumApi
    name: string
    distinct_ids: string[]
    properties: CohortPersonResultApiProperties
    /** @nullable */
    created_at: string | null
    /** @nullable */
    last_seen_at: string | null
    /** @nullable */
    is_identified: boolean | null
    matched_recordings: CohortPersonResultApiMatchedRecordingsItem[]
    /** @nullable */
    value_at_data_point: number | null
}

export interface CohortPersonsResponseApi {
    results: CohortPersonResultApi[]
    /** @nullable */
    next: string | null
    /** @nullable */
    previous: string | null
}

export interface PatchedRemovePersonRequestApi {
    /** Person UUID to remove from the cohort */
    person_id?: string
}

export interface CohortUsedInFlagApi {
    /** Feature flag database ID */
    id: number
    /** Feature flag key (URL slug) */
    key: string
    /**
     * Feature flag display name
     * @nullable
     */
    name: string | null
}

export interface CohortUsedInFlagsBlockApi {
    /** Feature flags referencing this cohort, capped at 100 results */
    results: CohortUsedInFlagApi[]
    /** Total number of feature flags referencing this cohort, before truncation */
    total: number
    /** True when more feature flags exist beyond the truncation cap */
    has_more: boolean
}

export interface CohortUsedInInsightApi {
    /** Insight database ID */
    id: number
    /** Insight short ID used for routing in the frontend */
    short_id: string
    /** Insight display name; falls back to derived name, then to 'Unnamed' when both are empty */
    name: string
}

export interface CohortUsedInInsightsBlockApi {
    /** Insights referencing this cohort, capped at 100 results */
    results: CohortUsedInInsightApi[]
    /** Total number of insights referencing this cohort, before truncation */
    total: number
    /** True when more insights exist beyond the truncation cap */
    has_more: boolean
}

export interface CohortUsedInCohortApi {
    /** Cohort database ID */
    id: number
    /** Cohort display name; falls back to 'Unnamed' when empty */
    name: string
}

export interface CohortUsedInCohortsBlockApi {
    /** Cohorts that include this cohort as a criterion, capped at 100 results */
    results: CohortUsedInCohortApi[]
    /** Total number of cohorts referencing this cohort, before truncation */
    total: number
    /** True when more cohorts exist beyond the truncation cap */
    has_more: boolean
}

export interface CohortUsedInResponseApi {
    /** Feature flags (active and inactive, excluding soft-deleted) that reference this cohort in their targeting conditions, with truncation metadata */
    feature_flags: CohortUsedInFlagsBlockApi
    /** Insights referencing this cohort with truncation metadata */
    insights: CohortUsedInInsightsBlockApi
    /** Other cohorts that include this cohort as a criterion, with truncation metadata */
    cohorts: CohortUsedInCohortsBlockApi
}

export type CohortsListParams = {
    /**
     * Return a basic payload that omits the heavy `filters`, `query`, and `groups` fields. Useful for pickers that only need id/name/count.
     */
    basic?: boolean
    /**
     * Set true to exclude behavioral (event-based) cohorts, which can't be used in feature flags or batch workflow audiences.
     */
    hide_behavioral_cohorts?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Optional. Match against cohort `name`. Returns exact (case-insensitive substring) matches only; if no exact match exists, returns similar (fuzzy trigram — typos, transpositions, prefix-as-you-type) matches instead. Each result's `search_match_type` is `exact` or `similar`. Results are ordered by relevance. When omitted, cohorts are ordered newest-first. Capped at 200 characters; longer queries return a 400 error.
     */
    search?: string
}

export type CohortsPersonsRetrieveParams = {
    format?: CohortsPersonsRetrieveFormat
    /**
     * Maximum number of persons to return per page (defaults to 100).
     */
    limit?: number
    /**
     * Number of persons to skip before starting to return results.
     */
    offset?: number
}

export type CohortsPersonsRetrieveFormat =
    (typeof CohortsPersonsRetrieveFormat)[keyof typeof CohortsPersonsRetrieveFormat]

export const CohortsPersonsRetrieveFormat = {
    Csv: 'csv',
    Json: 'json',
} as const
