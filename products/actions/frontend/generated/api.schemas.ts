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
 * * `contains` - contains
 * `regex` - regex
 * `exact` - exact
 */
export type UrlMatchingEnumApi = (typeof UrlMatchingEnumApi)[keyof typeof UrlMatchingEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const UrlMatchingEnumApi = {
    contains: 'contains',
    regex: 'regex',
    exact: 'exact',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const NullEnumApi = {} as const

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

export interface PaginatedActionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ActionApi[]
}

/**
 * Serializer mixin that resolves appropriate response for tags depending on license.
 */
export interface ActionApi {
    readonly id: number
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    description?: string
    tags?: unknown[]
    post_to_slack?: boolean
    /** @maxLength 1200 */
    slack_message_format?: string
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
    /** @nullable */
    pinned_at?: string | null
    readonly creation_context: string
    _create_in_folder?: string
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

/**
 * Serializer mixin that resolves appropriate response for tags depending on license.
 */
export interface PatchedActionApi {
    readonly id?: number
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    description?: string
    tags?: unknown[]
    post_to_slack?: boolean
    /** @maxLength 1200 */
    slack_message_format?: string
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
    /** @nullable */
    pinned_at?: string | null
    readonly creation_context?: string
    _create_in_folder?: string
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
}

export type ActionStepJSONApiPropertiesItem = { [key: string]: unknown }

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionStepJSONApiTextMatching = { ...UrlMatchingEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type ActionStepJSONApiTextMatching =
    | (typeof ActionStepJSONApiTextMatching)[keyof typeof ActionStepJSONApiTextMatching]
    | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionStepJSONApiHrefMatching = { ...UrlMatchingEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type ActionStepJSONApiHrefMatching =
    | (typeof ActionStepJSONApiHrefMatching)[keyof typeof ActionStepJSONApiHrefMatching]
    | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionStepJSONApiUrlMatching = { ...UrlMatchingEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type ActionStepJSONApiUrlMatching =
    | (typeof ActionStepJSONApiUrlMatching)[keyof typeof ActionStepJSONApiUrlMatching]
    | null

export interface ActionStepJSONApi {
    /** @nullable */
    event?: string | null
    /** @nullable */
    properties?: ActionStepJSONApiPropertiesItem[] | null
    /** @nullable */
    selector?: string | null
    /** @nullable */
    readonly selector_regex: string | null
    /** @nullable */
    tag_name?: string | null
    /** @nullable */
    text?: string | null
    /** @nullable */
    text_matching?: ActionStepJSONApiTextMatching
    /** @nullable */
    href?: string | null
    /** @nullable */
    href_matching?: ActionStepJSONApiHrefMatching
    /** @nullable */
    url?: string | null
    /** @nullable */
    url_matching?: ActionStepJSONApiUrlMatching
}

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const UserBasicApiRoleAtOrganization = { ...RoleAtOrganizationEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * @nullable
 */
export type UserBasicApiRoleAtOrganization =
    | (typeof UserBasicApiRoleAtOrganization)[keyof typeof UserBasicApiRoleAtOrganization]
    | null

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
    /** @nullable */
    role_at_organization?: UserBasicApiRoleAtOrganization
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionsListFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type ActionsCreateParams = {
    format?: ActionsCreateFormat
}

export type ActionsCreateFormat = (typeof ActionsCreateFormat)[keyof typeof ActionsCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionsCreateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type ActionsRetrieveParams = {
    format?: ActionsRetrieveFormat
}

export type ActionsRetrieveFormat = (typeof ActionsRetrieveFormat)[keyof typeof ActionsRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type ActionsUpdateParams = {
    format?: ActionsUpdateFormat
}

export type ActionsUpdateFormat = (typeof ActionsUpdateFormat)[keyof typeof ActionsUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionsUpdateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type ActionsPartialUpdateParams = {
    format?: ActionsPartialUpdateFormat
}

export type ActionsPartialUpdateFormat = (typeof ActionsPartialUpdateFormat)[keyof typeof ActionsPartialUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionsPartialUpdateFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type ActionsDestroyParams = {
    format?: ActionsDestroyFormat
}

export type ActionsDestroyFormat = (typeof ActionsDestroyFormat)[keyof typeof ActionsDestroyFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ActionsDestroyFormat = {
    csv: 'csv',
    json: 'json',
} as const
