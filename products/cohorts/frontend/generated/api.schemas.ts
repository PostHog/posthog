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
    engineering: 'engineering',
    data: 'data',
    product: 'product',
    founder: 'founder',
    leadership: 'leadership',
    marketing: 'marketing',
    sales: 'sales',
    other: 'other',
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
    static: 'static',
    person_property: 'person_property',
    behavioral: 'behavioral',
    realtime: 'realtime',
    analytical: 'analytical',
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
    /** Filters for the cohort. Examples:

        # Behavioral filter (performed event)
        {
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "OR",
                    "values": [{
                        "key": "address page viewed",
                        "type": "behavioral",
                        "value": "performed_event",
                        "negation": false,
                        "event_type": "events",
                        "time_value": "30",
                        "time_interval": "day"
                    }]
                }]
            }
        }

        # Person property filter
        {
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "AND",
                    "values": [{
                        "key": "promoCodes",
                        "type": "person",
                        "value": ["1234567890"],
                        "negation": false,
                        "operator": "exact"
                    }]
                }]
            }
        }

        # Cohort filter
        {
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "AND",
                    "values": [{
                        "key": "id",
                        "type": "cohort",
                        "value": 8814,
                        "negation": false
                    }]
                }]
            }
        } */
    filters?: unknown | null
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
    /** Filters for the cohort. Examples:

        # Behavioral filter (performed event)
        {
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "OR",
                    "values": [{
                        "key": "address page viewed",
                        "type": "behavioral",
                        "value": "performed_event",
                        "negation": false,
                        "event_type": "events",
                        "time_value": "30",
                        "time_interval": "day"
                    }]
                }]
            }
        }

        # Person property filter
        {
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "AND",
                    "values": [{
                        "key": "promoCodes",
                        "type": "person",
                        "value": ["1234567890"],
                        "negation": false,
                        "operator": "exact"
                    }]
                }]
            }
        }

        # Cohort filter
        {
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "AND",
                    "values": [{
                        "key": "id",
                        "type": "cohort",
                        "value": 8814,
                        "negation": false
                    }]
                }]
            }
        } */
    filters?: unknown | null
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
    csv: 'csv',
    json: 'json',
} as const
