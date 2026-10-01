/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface CrossProjectDashboardTileApi {
    readonly id: string
    /**
     * Id of the project the tile's insight belongs to.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    project_id: number
    /**
     * Id of the insight the tile renders.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    insight_id: number
    /** Grid position and size of the tile, keyed by layout size. */
    layouts?: unknown
    /**
     * Optional color applied to the tile.
     * @maxLength 400
     * @nullable
     */
    color?: string | null
    /** Filters applied to this tile only, overriding the dashboard's. Supports a date range and an interval. Filters carrying a project-specific id are rejected. */
    filters_overrides?: unknown
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
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
    Student: 'student',
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
 * Carries tile references only.
 *
 * The response holds no insight names, queries or results. Each reader fetches each tile from
 * that tile's own project endpoint, so their access, quota and cache key stay correct there.
 */
export interface CrossProjectDashboardApi {
    readonly id: string
    /**
     * Name shown in the dashboard list and page header.
     * @maxLength 400
     */
    name: string
    /** Optional longer description. */
    description?: string
    /** Dashboard-level filters applied to every tile. Supports a date range, an interval, and property filters that refer to a property by name. Filters carrying a project-specific id are rejected. */
    filters?: unknown
    readonly tiles: readonly CrossProjectDashboardTileApi[]
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedCrossProjectDashboardListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CrossProjectDashboardApi[]
}

export interface PaginatedCrossProjectDashboardTileListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CrossProjectDashboardTileApi[]
}

export interface PatchedCrossProjectDashboardTileApi {
    readonly id?: string
    /**
     * Id of the project the tile's insight belongs to.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    project_id?: number
    /**
     * Id of the insight the tile renders.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    insight_id?: number
    /** Grid position and size of the tile, keyed by layout size. */
    layouts?: unknown
    /**
     * Optional color applied to the tile.
     * @maxLength 400
     * @nullable
     */
    color?: string | null
    /** Filters applied to this tile only, overriding the dashboard's. Supports a date range and an interval. Filters carrying a project-specific id are rejected. */
    filters_overrides?: unknown
}

/**
 * Carries tile references only.
 *
 * The response holds no insight names, queries or results. Each reader fetches each tile from
 * that tile's own project endpoint, so their access, quota and cache key stay correct there.
 */
export interface PatchedCrossProjectDashboardApi {
    readonly id?: string
    /**
     * Name shown in the dashboard list and page header.
     * @maxLength 400
     */
    name?: string
    /** Optional longer description. */
    description?: string
    /** Dashboard-level filters applied to every tile. Supports a date range, an interval, and property filters that refer to a property by name. Filters carrying a project-specific id are rejected. */
    filters?: unknown
    readonly tiles?: readonly CrossProjectDashboardTileApi[]
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
}

export type CrossProjectDashboardsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CrossProjectDashboardsTilesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
