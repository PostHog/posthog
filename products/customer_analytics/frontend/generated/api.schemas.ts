/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface CustomerJourneyApi {
    readonly id: string
    insight: number
    /** @maxLength 400 */
    name: string
    /** @nullable */
    description?: string | null
    readonly created_at: string
    /** @nullable */
    readonly created_by: number | null
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedCustomerJourneyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CustomerJourneyApi[]
}

/**
 * * `person` - Person
 * `group_0` - Group 0
 * `group_1` - Group 1
 * `group_2` - Group 2
 * `group_3` - Group 3
 * `group_4` - Group 4
 */
export type CustomerProfileConfigScopeEnumApi =
    (typeof CustomerProfileConfigScopeEnumApi)[keyof typeof CustomerProfileConfigScopeEnumApi]

export const CustomerProfileConfigScopeEnumApi = {
    Person: 'person',
    Group0: 'group_0',
    Group1: 'group_1',
    Group2: 'group_2',
    Group3: 'group_3',
    Group4: 'group_4',
} as const

export interface CustomerProfileConfigApi {
    readonly id: string
    scope: CustomerProfileConfigScopeEnumApi
    content?: unknown | null
    sidebar?: unknown | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedCustomerProfileConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CustomerProfileConfigApi[]
}

/**
 * * `numeric` - numeric
 * `currency` - currency
 */
export type GroupUsageMetricFormatEnumApi =
    (typeof GroupUsageMetricFormatEnumApi)[keyof typeof GroupUsageMetricFormatEnumApi]

export const GroupUsageMetricFormatEnumApi = {
    Numeric: 'numeric',
    Currency: 'currency',
} as const

/**
 * * `number` - number
 * `sparkline` - sparkline
 */
export type GroupUsageMetricDisplayEnumApi =
    (typeof GroupUsageMetricDisplayEnumApi)[keyof typeof GroupUsageMetricDisplayEnumApi]

export const GroupUsageMetricDisplayEnumApi = {
    Number: 'number',
    Sparkline: 'sparkline',
} as const

/**
 * * `count` - count
 * `sum` - sum
 */
export type MathEnumApi = (typeof MathEnumApi)[keyof typeof MathEnumApi]

export const MathEnumApi = {
    Count: 'count',
    Sum: 'sum',
} as const

export interface GroupUsageMetricApi {
    readonly id: string
    /** @maxLength 255 */
    name: string
    format?: GroupUsageMetricFormatEnumApi
    /**
     * In days
     * @minimum -2147483648
     * @maximum 2147483647
     */
    interval?: number
    display?: GroupUsageMetricDisplayEnumApi
    filters: unknown
    math?: MathEnumApi
    /**
     * @maxLength 255
     * @nullable
     */
    math_property?: string | null
}

export interface PaginatedGroupUsageMetricListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: GroupUsageMetricApi[]
}

export interface PatchedGroupUsageMetricApi {
    readonly id?: string
    /** @maxLength 255 */
    name?: string
    format?: GroupUsageMetricFormatEnumApi
    /**
     * In days
     * @minimum -2147483648
     * @maximum 2147483647
     */
    interval?: number
    display?: GroupUsageMetricDisplayEnumApi
    filters?: unknown
    math?: MathEnumApi
    /**
     * @maxLength 255
     * @nullable
     */
    math_property?: string | null
}

export type CustomerJourneysListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CustomerProfileConfigsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type GroupsTypesMetricsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
