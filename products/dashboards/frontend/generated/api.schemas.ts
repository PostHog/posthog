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
 * * `default` - Default
 * `template` - Template
 * `duplicate` - Duplicate
 * `unlisted` - Unlisted (product-embedded)
 */
export type CreationModeEnumApi = (typeof CreationModeEnumApi)[keyof typeof CreationModeEnumApi]

export const CreationModeEnumApi = {
    default: 'default',
    template: 'template',
    duplicate: 'duplicate',
    unlisted: 'unlisted',
} as const

/**
 * * `21` - Everyone in the project can edit
 * `37` - Only those invited to this dashboard can edit
 */
export type DashboardRestrictionLevelApi =
    (typeof DashboardRestrictionLevelApi)[keyof typeof DashboardRestrictionLevelApi]

export const DashboardRestrictionLevelApi = {
    NUMBER_21: 21,
    NUMBER_37: 37,
} as const

export type EffectiveRestrictionLevelEnumApi =
    (typeof EffectiveRestrictionLevelEnumApi)[keyof typeof EffectiveRestrictionLevelEnumApi]

export const EffectiveRestrictionLevelEnumApi = {
    NUMBER_21: 21,
    NUMBER_37: 37,
} as const

export type EffectivePrivilegeLevelEnumApi =
    (typeof EffectivePrivilegeLevelEnumApi)[keyof typeof EffectivePrivilegeLevelEnumApi]

export const EffectivePrivilegeLevelEnumApi = {
    NUMBER_21: 21,
    NUMBER_37: 37,
} as const

/**
 * Serializer mixin that handles tags for objects.
 */
export interface DashboardBasicApi {
    readonly id: number
    /** @nullable */
    readonly name: string | null
    readonly description: string
    readonly pinned: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly last_accessed_at: string | null
    /** @nullable */
    readonly last_viewed_at: string | null
    readonly is_shared: boolean
    readonly deleted: boolean
    readonly creation_mode: CreationModeEnumApi
    tags?: unknown[]
    readonly restriction_level: DashboardRestrictionLevelApi
    readonly effective_restriction_level: EffectiveRestrictionLevelEnumApi
    readonly effective_privilege_level: EffectivePrivilegeLevelEnumApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    readonly access_control_version: string
    /** @nullable */
    readonly last_refresh: string | null
    readonly team_id: number
}

export interface PaginatedDashboardBasicListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DashboardBasicApi[]
}

export type DashboardApiFilters = { [key: string]: unknown }

/**
 * @nullable
 */
export type DashboardApiVariables = { [key: string]: unknown } | null | null

/**
 * @nullable
 */
export type DashboardApiPersistedFilters = { [key: string]: unknown } | null | null

/**
 * @nullable
 */
export type DashboardApiPersistedVariables = { [key: string]: unknown } | null | null

export type DashboardApiTilesItem = { [key: string]: unknown }

/**
 * Serializer mixin that handles tags for objects.
 */
export interface DashboardApi {
    readonly id: number
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    description?: string
    pinned?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    last_accessed_at?: string | null
    /** @nullable */
    readonly last_viewed_at: string | null
    readonly is_shared: boolean
    deleted?: boolean
    readonly creation_mode: CreationModeEnumApi
    readonly filters: DashboardApiFilters
    /** @nullable */
    readonly variables: DashboardApiVariables
    breakdown_colors?: unknown
    /** @nullable */
    data_color_theme_id?: number | null
    tags?: unknown[]
    /**
     * @minimum 0
     * @maximum 32767
     */
    restriction_level?: DashboardRestrictionLevelApi
    readonly effective_restriction_level: EffectiveRestrictionLevelEnumApi
    readonly effective_privilege_level: EffectivePrivilegeLevelEnumApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    readonly access_control_version: string
    /** @nullable */
    last_refresh?: string | null
    /** @nullable */
    readonly persisted_filters: DashboardApiPersistedFilters
    /** @nullable */
    readonly persisted_variables: DashboardApiPersistedVariables
    readonly team_id: number
    /** @nullable */
    readonly tiles: readonly DashboardApiTilesItem[] | null
    use_template?: string
    /** @nullable */
    use_dashboard?: number | null
    delete_insights?: boolean
    _create_in_folder?: string
}

export interface DashboardCollaboratorApi {
    readonly id: string
    readonly dashboard_id: number
    readonly user: UserBasicApi
    /**
     * @minimum 0
     * @maximum 32767
     */
    level: DashboardRestrictionLevelApi
    readonly added_at: string
    readonly updated_at: string
    user_uuid: string
}

export interface SharingConfigurationApi {
    readonly created_at: string
    enabled?: boolean
    /** @nullable */
    readonly access_token: string | null
    settings?: unknown | null
    password_required?: boolean
    readonly share_passwords: string
}

export type PatchedDashboardApiFilters = { [key: string]: unknown }

/**
 * @nullable
 */
export type PatchedDashboardApiVariables = { [key: string]: unknown } | null | null

/**
 * @nullable
 */
export type PatchedDashboardApiPersistedFilters = { [key: string]: unknown } | null | null

/**
 * @nullable
 */
export type PatchedDashboardApiPersistedVariables = { [key: string]: unknown } | null | null

export type PatchedDashboardApiTilesItem = { [key: string]: unknown }

/**
 * Serializer mixin that handles tags for objects.
 */
export interface PatchedDashboardApi {
    readonly id?: number
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    description?: string
    pinned?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    last_accessed_at?: string | null
    /** @nullable */
    readonly last_viewed_at?: string | null
    readonly is_shared?: boolean
    deleted?: boolean
    readonly creation_mode?: CreationModeEnumApi
    readonly filters?: PatchedDashboardApiFilters
    /** @nullable */
    readonly variables?: PatchedDashboardApiVariables
    breakdown_colors?: unknown
    /** @nullable */
    data_color_theme_id?: number | null
    tags?: unknown[]
    /**
     * @minimum 0
     * @maximum 32767
     */
    restriction_level?: DashboardRestrictionLevelApi
    readonly effective_restriction_level?: EffectiveRestrictionLevelEnumApi
    readonly effective_privilege_level?: EffectivePrivilegeLevelEnumApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
    readonly access_control_version?: string
    /** @nullable */
    last_refresh?: string | null
    /** @nullable */
    readonly persisted_filters?: PatchedDashboardApiPersistedFilters
    /** @nullable */
    readonly persisted_variables?: PatchedDashboardApiPersistedVariables
    readonly team_id?: number
    /** @nullable */
    readonly tiles?: readonly PatchedDashboardApiTilesItem[] | null
    use_template?: string
    /** @nullable */
    use_dashboard?: number | null
    delete_insights?: boolean
    _create_in_folder?: string
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

export type DashboardsListParams = {
    format?: DashboardsListFormat
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DashboardsListFormat = (typeof DashboardsListFormat)[keyof typeof DashboardsListFormat]

export const DashboardsListFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsCreateParams = {
    format?: DashboardsCreateFormat
}

export type DashboardsCreateFormat = (typeof DashboardsCreateFormat)[keyof typeof DashboardsCreateFormat]

export const DashboardsCreateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsRetrieveParams = {
    format?: DashboardsRetrieveFormat
}

export type DashboardsRetrieveFormat = (typeof DashboardsRetrieveFormat)[keyof typeof DashboardsRetrieveFormat]

export const DashboardsRetrieveFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsUpdateParams = {
    format?: DashboardsUpdateFormat
}

export type DashboardsUpdateFormat = (typeof DashboardsUpdateFormat)[keyof typeof DashboardsUpdateFormat]

export const DashboardsUpdateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsPartialUpdateParams = {
    format?: DashboardsPartialUpdateFormat
}

export type DashboardsPartialUpdateFormat =
    (typeof DashboardsPartialUpdateFormat)[keyof typeof DashboardsPartialUpdateFormat]

export const DashboardsPartialUpdateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsDestroyParams = {
    format?: DashboardsDestroyFormat
}

export type DashboardsDestroyFormat = (typeof DashboardsDestroyFormat)[keyof typeof DashboardsDestroyFormat]

export const DashboardsDestroyFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsMoveTilePartialUpdateParams = {
    format?: DashboardsMoveTilePartialUpdateFormat
}

export type DashboardsMoveTilePartialUpdateFormat =
    (typeof DashboardsMoveTilePartialUpdateFormat)[keyof typeof DashboardsMoveTilePartialUpdateFormat]

export const DashboardsMoveTilePartialUpdateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsStreamTilesRetrieveParams = {
    format?: DashboardsStreamTilesRetrieveFormat
}

export type DashboardsStreamTilesRetrieveFormat =
    (typeof DashboardsStreamTilesRetrieveFormat)[keyof typeof DashboardsStreamTilesRetrieveFormat]

export const DashboardsStreamTilesRetrieveFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsCreateFromTemplateJsonCreateParams = {
    format?: DashboardsCreateFromTemplateJsonCreateFormat
}

export type DashboardsCreateFromTemplateJsonCreateFormat =
    (typeof DashboardsCreateFromTemplateJsonCreateFormat)[keyof typeof DashboardsCreateFromTemplateJsonCreateFormat]

export const DashboardsCreateFromTemplateJsonCreateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsCreateUnlistedDashboardCreateParams = {
    format?: DashboardsCreateUnlistedDashboardCreateFormat
}

export type DashboardsCreateUnlistedDashboardCreateFormat =
    (typeof DashboardsCreateUnlistedDashboardCreateFormat)[keyof typeof DashboardsCreateUnlistedDashboardCreateFormat]

export const DashboardsCreateUnlistedDashboardCreateFormat = {
    json: 'json',
    txt: 'txt',
} as const

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

export type DashboardsList2Params = {
    format?: DashboardsList2Format
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DashboardsList2Format = (typeof DashboardsList2Format)[keyof typeof DashboardsList2Format]

export const DashboardsList2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsCreate2Params = {
    format?: DashboardsCreate2Format
}

export type DashboardsCreate2Format = (typeof DashboardsCreate2Format)[keyof typeof DashboardsCreate2Format]

export const DashboardsCreate2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsRetrieve2Params = {
    format?: DashboardsRetrieve2Format
}

export type DashboardsRetrieve2Format = (typeof DashboardsRetrieve2Format)[keyof typeof DashboardsRetrieve2Format]

export const DashboardsRetrieve2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsUpdate2Params = {
    format?: DashboardsUpdate2Format
}

export type DashboardsUpdate2Format = (typeof DashboardsUpdate2Format)[keyof typeof DashboardsUpdate2Format]

export const DashboardsUpdate2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsPartialUpdate2Params = {
    format?: DashboardsPartialUpdate2Format
}

export type DashboardsPartialUpdate2Format =
    (typeof DashboardsPartialUpdate2Format)[keyof typeof DashboardsPartialUpdate2Format]

export const DashboardsPartialUpdate2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsDestroy2Params = {
    format?: DashboardsDestroy2Format
}

export type DashboardsDestroy2Format = (typeof DashboardsDestroy2Format)[keyof typeof DashboardsDestroy2Format]

export const DashboardsDestroy2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsMoveTilePartialUpdate2Params = {
    format?: DashboardsMoveTilePartialUpdate2Format
}

export type DashboardsMoveTilePartialUpdate2Format =
    (typeof DashboardsMoveTilePartialUpdate2Format)[keyof typeof DashboardsMoveTilePartialUpdate2Format]

export const DashboardsMoveTilePartialUpdate2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsStreamTilesRetrieve2Params = {
    format?: DashboardsStreamTilesRetrieve2Format
}

export type DashboardsStreamTilesRetrieve2Format =
    (typeof DashboardsStreamTilesRetrieve2Format)[keyof typeof DashboardsStreamTilesRetrieve2Format]

export const DashboardsStreamTilesRetrieve2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsCreateFromTemplateJsonCreate2Params = {
    format?: DashboardsCreateFromTemplateJsonCreate2Format
}

export type DashboardsCreateFromTemplateJsonCreate2Format =
    (typeof DashboardsCreateFromTemplateJsonCreate2Format)[keyof typeof DashboardsCreateFromTemplateJsonCreate2Format]

export const DashboardsCreateFromTemplateJsonCreate2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsCreateUnlistedDashboardCreate2Params = {
    format?: DashboardsCreateUnlistedDashboardCreate2Format
}

export type DashboardsCreateUnlistedDashboardCreate2Format =
    (typeof DashboardsCreateUnlistedDashboardCreate2Format)[keyof typeof DashboardsCreateUnlistedDashboardCreate2Format]

export const DashboardsCreateUnlistedDashboardCreate2Format = {
    json: 'json',
    txt: 'txt',
} as const

export type DataColorThemesList2Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
