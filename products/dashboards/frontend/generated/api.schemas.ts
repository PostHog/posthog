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

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const NullEnumApi = {} as const

export type UserBasicApiHedgehogConfigAnyOf = { [key: string]: unknown }

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = UserBasicApiHedgehogConfigAnyOf | null | null

export type UserBasicApiRoleAtOrganization = RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi

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
    role_at_organization?: UserBasicApiRoleAtOrganization
}

export interface DataColorThemeApi {
    readonly id: number
    /** @maxLength 100 */
    name: string
    colors?: unknown
    readonly is_global: string
    /** @nullable */
    readonly created_at: string | null
    readonly created_by: UserBasicApi
}

export interface PaginatedDataColorThemeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataColorThemeApi[]
}

export interface PatchedDataColorThemeApi {
    readonly id?: number
    /** @maxLength 100 */
    name?: string
    colors?: unknown
    readonly is_global?: string
    /** @nullable */
    readonly created_at?: string | null
    readonly created_by?: UserBasicApi
}

export type EnvironmentsDataColorThemesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DataColorThemesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
