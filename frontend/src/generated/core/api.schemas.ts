/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi
}

/**
 * * `default` - Default
 * `template` - Template
 * `duplicate` - Duplicate
 * `unlisted` - Unlisted (product-embedded)
 */
export type CreationModeEnumApi = (typeof CreationModeEnumApi)[keyof typeof CreationModeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardRestrictionLevelApi = {
    NUMBER_21: 21,
    NUMBER_37: 37,
} as const

export type EffectiveRestrictionLevelEnumApi =
    (typeof EffectiveRestrictionLevelEnumApi)[keyof typeof EffectiveRestrictionLevelEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EffectiveRestrictionLevelEnumApi = {
    NUMBER_21: 21,
    NUMBER_37: 37,
} as const

export type EffectivePrivilegeLevelEnumApi =
    (typeof EffectivePrivilegeLevelEnumApi)[keyof typeof EffectivePrivilegeLevelEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EffectivePrivilegeLevelEnumApi = {
    NUMBER_21: 21,
    NUMBER_37: 37,
} as const

/**
 * Serializer mixin that resolves appropriate response for tags depending on license.
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
 * Serializer mixin that resolves appropriate response for tags depending on license.
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

export interface SharingConfigurationApi {
    readonly created_at: string
    enabled?: boolean
    /** @nullable */
    readonly access_token: string | null
    settings?: unknown
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
 * Serializer mixin that resolves appropriate response for tags depending on license.
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

/**
 * * `image/png` - image/png
 * `application/pdf` - application/pdf
 * `text/csv` - text/csv
 * `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
 * `video/webm` - video/webm
 * `video/mp4` - video/mp4
 * `image/gif` - image/gif
 * `application/json` - application/json
 */
export type ExportFormatEnumApi = (typeof ExportFormatEnumApi)[keyof typeof ExportFormatEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ExportFormatEnumApi = {
    'image/png': 'image/png',
    'application/pdf': 'application/pdf',
    'text/csv': 'text/csv',
    'application/vndopenxmlformats-officedocumentspreadsheetmlsheet':
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'video/webm': 'video/webm',
    'video/mp4': 'video/mp4',
    'image/gif': 'image/gif',
    'application/json': 'application/json',
} as const

/**
 * Standard ExportedAsset serializer that doesn't return content.
 */
export interface ExportedAssetApi {
    readonly id: number
    /** @nullable */
    dashboard?: number | null
    /** @nullable */
    insight?: number | null
    export_format: ExportFormatEnumApi
    readonly created_at: string
    readonly has_content: string
    export_context?: unknown
    readonly filename: string
    /** @nullable */
    readonly expires_after: string | null
    /** @nullable */
    readonly exception: string | null
}

export interface PaginatedExportedAssetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExportedAssetApi[]
}

export interface FileSystemApi {
    readonly id: string
    path: string
    /** @nullable */
    readonly depth: number | null
    /** @maxLength 100 */
    type?: string
    /**
     * @maxLength 100
     * @nullable
     */
    ref?: string | null
    /** @nullable */
    href?: string | null
    meta?: unknown
    /** @nullable */
    shortcut?: boolean | null
    readonly created_at: string
    /** @nullable */
    readonly last_viewed_at: string | null
}

export interface PaginatedFileSystemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: FileSystemApi[]
}

export interface PatchedFileSystemApi {
    readonly id?: string
    path?: string
    /** @nullable */
    readonly depth?: number | null
    /** @maxLength 100 */
    type?: string
    /**
     * @maxLength 100
     * @nullable
     */
    ref?: string | null
    /** @nullable */
    href?: string | null
    meta?: unknown
    /** @nullable */
    shortcut?: boolean | null
    readonly created_at?: string
    /** @nullable */
    readonly last_viewed_at?: string | null
}

export interface GroupApi {
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    group_type_index: number
    /** @maxLength 400 */
    group_key: string
    group_properties?: unknown
    readonly created_at: string
}

export interface PaginatedGroupListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: GroupApi[]
}

export interface CreateGroupApi {
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    group_type_index: number
    /** @maxLength 400 */
    group_key: string
    group_properties?: unknown
}

/**
 * * `slack` - Slack
 * `salesforce` - Salesforce
 * `hubspot` - Hubspot
 * `google-pubsub` - Google Pubsub
 * `google-cloud-storage` - Google Cloud Storage
 * `google-ads` - Google Ads
 * `google-sheets` - Google Sheets
 * `snapchat` - Snapchat
 * `linkedin-ads` - Linkedin Ads
 * `reddit-ads` - Reddit Ads
 * `tiktok-ads` - Tiktok Ads
 * `bing-ads` - Bing Ads
 * `intercom` - Intercom
 * `email` - Email
 * `linear` - Linear
 * `github` - Github
 * `gitlab` - Gitlab
 * `meta-ads` - Meta Ads
 * `twilio` - Twilio
 * `clickup` - Clickup
 * `vercel` - Vercel
 * `databricks` - Databricks
 * `azure-blob` - Azure Blob
 * `firebase` - Firebase
 */
export type Kind9f6EnumApi = (typeof Kind9f6EnumApi)[keyof typeof Kind9f6EnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const Kind9f6EnumApi = {
    slack: 'slack',
    salesforce: 'salesforce',
    hubspot: 'hubspot',
    'google-pubsub': 'google-pubsub',
    'google-cloud-storage': 'google-cloud-storage',
    'google-ads': 'google-ads',
    'google-sheets': 'google-sheets',
    snapchat: 'snapchat',
    'linkedin-ads': 'linkedin-ads',
    'reddit-ads': 'reddit-ads',
    'tiktok-ads': 'tiktok-ads',
    'bing-ads': 'bing-ads',
    intercom: 'intercom',
    email: 'email',
    linear: 'linear',
    github: 'github',
    gitlab: 'gitlab',
    'meta-ads': 'meta-ads',
    twilio: 'twilio',
    clickup: 'clickup',
    vercel: 'vercel',
    databricks: 'databricks',
    'azure-blob': 'azure-blob',
    firebase: 'firebase',
} as const

/**
 * Standard Integration serializer.
 */
export interface IntegrationApi {
    readonly id: number
    kind: Kind9f6EnumApi
    config?: unknown
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly errors: string
    readonly display_name: string
}

export interface PaginatedIntegrationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: IntegrationApi[]
}

/**
 * * `email` - Email
 * `slack` - Slack
 * `webhook` - Webhook
 */
export type TargetTypeEnumApi = (typeof TargetTypeEnumApi)[keyof typeof TargetTypeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const TargetTypeEnumApi = {
    email: 'email',
    slack: 'slack',
    webhook: 'webhook',
} as const

/**
 * * `daily` - Daily
 * `weekly` - Weekly
 * `monthly` - Monthly
 * `yearly` - Yearly
 */
export type FrequencyEnumApi = (typeof FrequencyEnumApi)[keyof typeof FrequencyEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const FrequencyEnumApi = {
    daily: 'daily',
    weekly: 'weekly',
    monthly: 'monthly',
    yearly: 'yearly',
} as const

/**
 * * `monday` - Monday
 * `tuesday` - Tuesday
 * `wednesday` - Wednesday
 * `thursday` - Thursday
 * `friday` - Friday
 * `saturday` - Saturday
 * `sunday` - Sunday
 */
export type ByweekdayEnumApi = (typeof ByweekdayEnumApi)[keyof typeof ByweekdayEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ByweekdayEnumApi = {
    monday: 'monday',
    tuesday: 'tuesday',
    wednesday: 'wednesday',
    thursday: 'thursday',
    friday: 'friday',
    saturday: 'saturday',
    sunday: 'sunday',
} as const

/**
 * Standard Subscription serializer.
 */
export interface SubscriptionApi {
    readonly id: number
    /** @nullable */
    dashboard?: number | null
    /** @nullable */
    insight?: number | null
    target_type: TargetTypeEnumApi
    target_value: string
    frequency: FrequencyEnumApi
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    interval?: number
    /** @nullable */
    byweekday?: ByweekdayEnumApi[] | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    bysetpos?: number | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    count?: number | null
    start_date: string
    /** @nullable */
    until_date?: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    deleted?: boolean
    /**
     * @maxLength 100
     * @nullable
     */
    title?: string | null
    readonly summary: string
    /** @nullable */
    readonly next_delivery_date: string | null
    /** @nullable */
    invite_message?: string | null
}

export interface PaginatedSubscriptionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SubscriptionApi[]
}

/**
 * Standard Subscription serializer.
 */
export interface PatchedSubscriptionApi {
    readonly id?: number
    /** @nullable */
    dashboard?: number | null
    /** @nullable */
    insight?: number | null
    target_type?: TargetTypeEnumApi
    target_value?: string
    frequency?: FrequencyEnumApi
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    interval?: number
    /** @nullable */
    byweekday?: ByweekdayEnumApi[] | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    bysetpos?: number | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    count?: number | null
    start_date?: string
    /** @nullable */
    until_date?: string | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    deleted?: boolean
    /**
     * @maxLength 100
     * @nullable
     */
    title?: string | null
    readonly summary?: string
    /** @nullable */
    readonly next_delivery_date?: string | null
    /** @nullable */
    invite_message?: string | null
}

export interface OrganizationDomainApi {
    readonly id: string
    /** @maxLength 128 */
    domain: string
    /** Determines whether a domain is verified or not. */
    readonly is_verified: boolean
    /** @nullable */
    readonly verified_at: string | null
    readonly verification_challenge: string
    jit_provisioning_enabled?: boolean
    /** @maxLength 28 */
    sso_enforcement?: string
    /** Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places). */
    readonly has_saml: boolean
    /**
     * @maxLength 512
     * @nullable
     */
    saml_entity_id?: string | null
    /**
     * @maxLength 512
     * @nullable
     */
    saml_acs_url?: string | null
    /** @nullable */
    saml_x509_cert?: string | null
    /** Returns whether SCIM is configured and enabled for this domain. */
    readonly has_scim: boolean
    scim_enabled?: boolean
    /** @nullable */
    readonly scim_base_url: string | null
    /** @nullable */
    readonly scim_bearer_token: string | null
}

export interface PaginatedOrganizationDomainListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationDomainApi[]
}

export interface PatchedOrganizationDomainApi {
    readonly id?: string
    /** @maxLength 128 */
    domain?: string
    /** Determines whether a domain is verified or not. */
    readonly is_verified?: boolean
    /** @nullable */
    readonly verified_at?: string | null
    readonly verification_challenge?: string
    jit_provisioning_enabled?: boolean
    /** @maxLength 28 */
    sso_enforcement?: string
    /** Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places). */
    readonly has_saml?: boolean
    /**
     * @maxLength 512
     * @nullable
     */
    saml_entity_id?: string | null
    /**
     * @maxLength 512
     * @nullable
     */
    saml_acs_url?: string | null
    /** @nullable */
    saml_x509_cert?: string | null
    /** Returns whether SCIM is configured and enabled for this domain. */
    readonly has_scim?: boolean
    scim_enabled?: boolean
    /** @nullable */
    readonly scim_base_url?: string | null
    /** @nullable */
    readonly scim_bearer_token?: string | null
}

/**
 * * `1` - member
 * `8` - administrator
 * `15` - owner
 */
export type OrganizationMembershipLevelApi =
    (typeof OrganizationMembershipLevelApi)[keyof typeof OrganizationMembershipLevelApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const OrganizationMembershipLevelApi = {
    NUMBER_1: 1,
    NUMBER_8: 8,
    NUMBER_15: 15,
} as const

export interface OrganizationInviteApi {
    readonly id: string
    /** @maxLength 254 */
    target_email: string
    /** @maxLength 30 */
    first_name?: string
    readonly emailing_attempt_made: boolean
    /**
     * @minimum 0
     * @maximum 32767
     */
    level?: OrganizationMembershipLevelApi
    /** Check if invite is older than INVITE_DAYS_VALIDITY days. */
    readonly is_expired: boolean
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    message?: string | null
    /** List of team IDs and corresponding access levels to private projects. */
    private_project_access?: unknown
    send_email?: boolean
    combine_pending_invites?: boolean
}

export interface PaginatedOrganizationInviteListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationInviteApi[]
}

export interface OrganizationMemberApi {
    readonly id: string
    readonly user: UserBasicApi
    /**
     * @minimum 0
     * @maximum 32767
     */
    level?: OrganizationMembershipLevelApi
    readonly joined_at: string
    readonly updated_at: string
    readonly is_2fa_enabled: boolean
    readonly has_social_auth: boolean
    readonly last_login: string
}

export interface PaginatedOrganizationMemberListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationMemberApi[]
}

export interface PatchedOrganizationMemberApi {
    readonly id?: string
    readonly user?: UserBasicApi
    /**
     * @minimum 0
     * @maximum 32767
     */
    level?: OrganizationMembershipLevelApi
    readonly joined_at?: string
    readonly updated_at?: string
    readonly is_2fa_enabled?: boolean
    readonly has_social_auth?: boolean
    readonly last_login?: string
}

/**
 * * `Africa/Abidjan` - Africa/Abidjan
 * `Africa/Accra` - Africa/Accra
 * `Africa/Addis_Ababa` - Africa/Addis_Ababa
 * `Africa/Algiers` - Africa/Algiers
 * `Africa/Asmara` - Africa/Asmara
 * `Africa/Asmera` - Africa/Asmera
 * `Africa/Bamako` - Africa/Bamako
 * `Africa/Bangui` - Africa/Bangui
 * `Africa/Banjul` - Africa/Banjul
 * `Africa/Bissau` - Africa/Bissau
 * `Africa/Blantyre` - Africa/Blantyre
 * `Africa/Brazzaville` - Africa/Brazzaville
 * `Africa/Bujumbura` - Africa/Bujumbura
 * `Africa/Cairo` - Africa/Cairo
 * `Africa/Casablanca` - Africa/Casablanca
 * `Africa/Ceuta` - Africa/Ceuta
 * `Africa/Conakry` - Africa/Conakry
 * `Africa/Dakar` - Africa/Dakar
 * `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam
 * `Africa/Djibouti` - Africa/Djibouti
 * `Africa/Douala` - Africa/Douala
 * `Africa/El_Aaiun` - Africa/El_Aaiun
 * `Africa/Freetown` - Africa/Freetown
 * `Africa/Gaborone` - Africa/Gaborone
 * `Africa/Harare` - Africa/Harare
 * `Africa/Johannesburg` - Africa/Johannesburg
 * `Africa/Juba` - Africa/Juba
 * `Africa/Kampala` - Africa/Kampala
 * `Africa/Khartoum` - Africa/Khartoum
 * `Africa/Kigali` - Africa/Kigali
 * `Africa/Kinshasa` - Africa/Kinshasa
 * `Africa/Lagos` - Africa/Lagos
 * `Africa/Libreville` - Africa/Libreville
 * `Africa/Lome` - Africa/Lome
 * `Africa/Luanda` - Africa/Luanda
 * `Africa/Lubumbashi` - Africa/Lubumbashi
 * `Africa/Lusaka` - Africa/Lusaka
 * `Africa/Malabo` - Africa/Malabo
 * `Africa/Maputo` - Africa/Maputo
 * `Africa/Maseru` - Africa/Maseru
 * `Africa/Mbabane` - Africa/Mbabane
 * `Africa/Mogadishu` - Africa/Mogadishu
 * `Africa/Monrovia` - Africa/Monrovia
 * `Africa/Nairobi` - Africa/Nairobi
 * `Africa/Ndjamena` - Africa/Ndjamena
 * `Africa/Niamey` - Africa/Niamey
 * `Africa/Nouakchott` - Africa/Nouakchott
 * `Africa/Ouagadougou` - Africa/Ouagadougou
 * `Africa/Porto-Novo` - Africa/Porto-Novo
 * `Africa/Sao_Tome` - Africa/Sao_Tome
 * `Africa/Timbuktu` - Africa/Timbuktu
 * `Africa/Tripoli` - Africa/Tripoli
 * `Africa/Tunis` - Africa/Tunis
 * `Africa/Windhoek` - Africa/Windhoek
 * `America/Adak` - America/Adak
 * `America/Anchorage` - America/Anchorage
 * `America/Anguilla` - America/Anguilla
 * `America/Antigua` - America/Antigua
 * `America/Araguaina` - America/Araguaina
 * `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires
 * `America/Argentina/Catamarca` - America/Argentina/Catamarca
 * `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia
 * `America/Argentina/Cordoba` - America/Argentina/Cordoba
 * `America/Argentina/Jujuy` - America/Argentina/Jujuy
 * `America/Argentina/La_Rioja` - America/Argentina/La_Rioja
 * `America/Argentina/Mendoza` - America/Argentina/Mendoza
 * `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos
 * `America/Argentina/Salta` - America/Argentina/Salta
 * `America/Argentina/San_Juan` - America/Argentina/San_Juan
 * `America/Argentina/San_Luis` - America/Argentina/San_Luis
 * `America/Argentina/Tucuman` - America/Argentina/Tucuman
 * `America/Argentina/Ushuaia` - America/Argentina/Ushuaia
 * `America/Aruba` - America/Aruba
 * `America/Asuncion` - America/Asuncion
 * `America/Atikokan` - America/Atikokan
 * `America/Atka` - America/Atka
 * `America/Bahia` - America/Bahia
 * `America/Bahia_Banderas` - America/Bahia_Banderas
 * `America/Barbados` - America/Barbados
 * `America/Belem` - America/Belem
 * `America/Belize` - America/Belize
 * `America/Blanc-Sablon` - America/Blanc-Sablon
 * `America/Boa_Vista` - America/Boa_Vista
 * `America/Bogota` - America/Bogota
 * `America/Boise` - America/Boise
 * `America/Buenos_Aires` - America/Buenos_Aires
 * `America/Cambridge_Bay` - America/Cambridge_Bay
 * `America/Campo_Grande` - America/Campo_Grande
 * `America/Cancun` - America/Cancun
 * `America/Caracas` - America/Caracas
 * `America/Catamarca` - America/Catamarca
 * `America/Cayenne` - America/Cayenne
 * `America/Cayman` - America/Cayman
 * `America/Chicago` - America/Chicago
 * `America/Chihuahua` - America/Chihuahua
 * `America/Ciudad_Juarez` - America/Ciudad_Juarez
 * `America/Coral_Harbour` - America/Coral_Harbour
 * `America/Cordoba` - America/Cordoba
 * `America/Costa_Rica` - America/Costa_Rica
 * `America/Creston` - America/Creston
 * `America/Cuiaba` - America/Cuiaba
 * `America/Curacao` - America/Curacao
 * `America/Danmarkshavn` - America/Danmarkshavn
 * `America/Dawson` - America/Dawson
 * `America/Dawson_Creek` - America/Dawson_Creek
 * `America/Denver` - America/Denver
 * `America/Detroit` - America/Detroit
 * `America/Dominica` - America/Dominica
 * `America/Edmonton` - America/Edmonton
 * `America/Eirunepe` - America/Eirunepe
 * `America/El_Salvador` - America/El_Salvador
 * `America/Ensenada` - America/Ensenada
 * `America/Fort_Nelson` - America/Fort_Nelson
 * `America/Fort_Wayne` - America/Fort_Wayne
 * `America/Fortaleza` - America/Fortaleza
 * `America/Glace_Bay` - America/Glace_Bay
 * `America/Godthab` - America/Godthab
 * `America/Goose_Bay` - America/Goose_Bay
 * `America/Grand_Turk` - America/Grand_Turk
 * `America/Grenada` - America/Grenada
 * `America/Guadeloupe` - America/Guadeloupe
 * `America/Guatemala` - America/Guatemala
 * `America/Guayaquil` - America/Guayaquil
 * `America/Guyana` - America/Guyana
 * `America/Halifax` - America/Halifax
 * `America/Havana` - America/Havana
 * `America/Hermosillo` - America/Hermosillo
 * `America/Indiana/Indianapolis` - America/Indiana/Indianapolis
 * `America/Indiana/Knox` - America/Indiana/Knox
 * `America/Indiana/Marengo` - America/Indiana/Marengo
 * `America/Indiana/Petersburg` - America/Indiana/Petersburg
 * `America/Indiana/Tell_City` - America/Indiana/Tell_City
 * `America/Indiana/Vevay` - America/Indiana/Vevay
 * `America/Indiana/Vincennes` - America/Indiana/Vincennes
 * `America/Indiana/Winamac` - America/Indiana/Winamac
 * `America/Indianapolis` - America/Indianapolis
 * `America/Inuvik` - America/Inuvik
 * `America/Iqaluit` - America/Iqaluit
 * `America/Jamaica` - America/Jamaica
 * `America/Jujuy` - America/Jujuy
 * `America/Juneau` - America/Juneau
 * `America/Kentucky/Louisville` - America/Kentucky/Louisville
 * `America/Kentucky/Monticello` - America/Kentucky/Monticello
 * `America/Knox_IN` - America/Knox_IN
 * `America/Kralendijk` - America/Kralendijk
 * `America/La_Paz` - America/La_Paz
 * `America/Lima` - America/Lima
 * `America/Los_Angeles` - America/Los_Angeles
 * `America/Louisville` - America/Louisville
 * `America/Lower_Princes` - America/Lower_Princes
 * `America/Maceio` - America/Maceio
 * `America/Managua` - America/Managua
 * `America/Manaus` - America/Manaus
 * `America/Marigot` - America/Marigot
 * `America/Martinique` - America/Martinique
 * `America/Matamoros` - America/Matamoros
 * `America/Mazatlan` - America/Mazatlan
 * `America/Mendoza` - America/Mendoza
 * `America/Menominee` - America/Menominee
 * `America/Merida` - America/Merida
 * `America/Metlakatla` - America/Metlakatla
 * `America/Mexico_City` - America/Mexico_City
 * `America/Miquelon` - America/Miquelon
 * `America/Moncton` - America/Moncton
 * `America/Monterrey` - America/Monterrey
 * `America/Montevideo` - America/Montevideo
 * `America/Montreal` - America/Montreal
 * `America/Montserrat` - America/Montserrat
 * `America/Nassau` - America/Nassau
 * `America/New_York` - America/New_York
 * `America/Nipigon` - America/Nipigon
 * `America/Nome` - America/Nome
 * `America/Noronha` - America/Noronha
 * `America/North_Dakota/Beulah` - America/North_Dakota/Beulah
 * `America/North_Dakota/Center` - America/North_Dakota/Center
 * `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem
 * `America/Nuuk` - America/Nuuk
 * `America/Ojinaga` - America/Ojinaga
 * `America/Panama` - America/Panama
 * `America/Pangnirtung` - America/Pangnirtung
 * `America/Paramaribo` - America/Paramaribo
 * `America/Phoenix` - America/Phoenix
 * `America/Port-au-Prince` - America/Port-au-Prince
 * `America/Port_of_Spain` - America/Port_of_Spain
 * `America/Porto_Acre` - America/Porto_Acre
 * `America/Porto_Velho` - America/Porto_Velho
 * `America/Puerto_Rico` - America/Puerto_Rico
 * `America/Punta_Arenas` - America/Punta_Arenas
 * `America/Rainy_River` - America/Rainy_River
 * `America/Rankin_Inlet` - America/Rankin_Inlet
 * `America/Recife` - America/Recife
 * `America/Regina` - America/Regina
 * `America/Resolute` - America/Resolute
 * `America/Rio_Branco` - America/Rio_Branco
 * `America/Rosario` - America/Rosario
 * `America/Santa_Isabel` - America/Santa_Isabel
 * `America/Santarem` - America/Santarem
 * `America/Santiago` - America/Santiago
 * `America/Santo_Domingo` - America/Santo_Domingo
 * `America/Sao_Paulo` - America/Sao_Paulo
 * `America/Scoresbysund` - America/Scoresbysund
 * `America/Shiprock` - America/Shiprock
 * `America/Sitka` - America/Sitka
 * `America/St_Barthelemy` - America/St_Barthelemy
 * `America/St_Johns` - America/St_Johns
 * `America/St_Kitts` - America/St_Kitts
 * `America/St_Lucia` - America/St_Lucia
 * `America/St_Thomas` - America/St_Thomas
 * `America/St_Vincent` - America/St_Vincent
 * `America/Swift_Current` - America/Swift_Current
 * `America/Tegucigalpa` - America/Tegucigalpa
 * `America/Thule` - America/Thule
 * `America/Thunder_Bay` - America/Thunder_Bay
 * `America/Tijuana` - America/Tijuana
 * `America/Toronto` - America/Toronto
 * `America/Tortola` - America/Tortola
 * `America/Vancouver` - America/Vancouver
 * `America/Virgin` - America/Virgin
 * `America/Whitehorse` - America/Whitehorse
 * `America/Winnipeg` - America/Winnipeg
 * `America/Yakutat` - America/Yakutat
 * `America/Yellowknife` - America/Yellowknife
 * `Antarctica/Casey` - Antarctica/Casey
 * `Antarctica/Davis` - Antarctica/Davis
 * `Antarctica/DumontDUrville` - Antarctica/DumontDUrville
 * `Antarctica/Macquarie` - Antarctica/Macquarie
 * `Antarctica/Mawson` - Antarctica/Mawson
 * `Antarctica/McMurdo` - Antarctica/McMurdo
 * `Antarctica/Palmer` - Antarctica/Palmer
 * `Antarctica/Rothera` - Antarctica/Rothera
 * `Antarctica/South_Pole` - Antarctica/South_Pole
 * `Antarctica/Syowa` - Antarctica/Syowa
 * `Antarctica/Troll` - Antarctica/Troll
 * `Antarctica/Vostok` - Antarctica/Vostok
 * `Arctic/Longyearbyen` - Arctic/Longyearbyen
 * `Asia/Aden` - Asia/Aden
 * `Asia/Almaty` - Asia/Almaty
 * `Asia/Amman` - Asia/Amman
 * `Asia/Anadyr` - Asia/Anadyr
 * `Asia/Aqtau` - Asia/Aqtau
 * `Asia/Aqtobe` - Asia/Aqtobe
 * `Asia/Ashgabat` - Asia/Ashgabat
 * `Asia/Ashkhabad` - Asia/Ashkhabad
 * `Asia/Atyrau` - Asia/Atyrau
 * `Asia/Baghdad` - Asia/Baghdad
 * `Asia/Bahrain` - Asia/Bahrain
 * `Asia/Baku` - Asia/Baku
 * `Asia/Bangkok` - Asia/Bangkok
 * `Asia/Barnaul` - Asia/Barnaul
 * `Asia/Beirut` - Asia/Beirut
 * `Asia/Bishkek` - Asia/Bishkek
 * `Asia/Brunei` - Asia/Brunei
 * `Asia/Calcutta` - Asia/Calcutta
 * `Asia/Chita` - Asia/Chita
 * `Asia/Choibalsan` - Asia/Choibalsan
 * `Asia/Chongqing` - Asia/Chongqing
 * `Asia/Chungking` - Asia/Chungking
 * `Asia/Colombo` - Asia/Colombo
 * `Asia/Dacca` - Asia/Dacca
 * `Asia/Damascus` - Asia/Damascus
 * `Asia/Dhaka` - Asia/Dhaka
 * `Asia/Dili` - Asia/Dili
 * `Asia/Dubai` - Asia/Dubai
 * `Asia/Dushanbe` - Asia/Dushanbe
 * `Asia/Famagusta` - Asia/Famagusta
 * `Asia/Gaza` - Asia/Gaza
 * `Asia/Harbin` - Asia/Harbin
 * `Asia/Hebron` - Asia/Hebron
 * `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh
 * `Asia/Hong_Kong` - Asia/Hong_Kong
 * `Asia/Hovd` - Asia/Hovd
 * `Asia/Irkutsk` - Asia/Irkutsk
 * `Asia/Istanbul` - Asia/Istanbul
 * `Asia/Jakarta` - Asia/Jakarta
 * `Asia/Jayapura` - Asia/Jayapura
 * `Asia/Jerusalem` - Asia/Jerusalem
 * `Asia/Kabul` - Asia/Kabul
 * `Asia/Kamchatka` - Asia/Kamchatka
 * `Asia/Karachi` - Asia/Karachi
 * `Asia/Kashgar` - Asia/Kashgar
 * `Asia/Kathmandu` - Asia/Kathmandu
 * `Asia/Katmandu` - Asia/Katmandu
 * `Asia/Khandyga` - Asia/Khandyga
 * `Asia/Kolkata` - Asia/Kolkata
 * `Asia/Krasnoyarsk` - Asia/Krasnoyarsk
 * `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur
 * `Asia/Kuching` - Asia/Kuching
 * `Asia/Kuwait` - Asia/Kuwait
 * `Asia/Macao` - Asia/Macao
 * `Asia/Macau` - Asia/Macau
 * `Asia/Magadan` - Asia/Magadan
 * `Asia/Makassar` - Asia/Makassar
 * `Asia/Manila` - Asia/Manila
 * `Asia/Muscat` - Asia/Muscat
 * `Asia/Nicosia` - Asia/Nicosia
 * `Asia/Novokuznetsk` - Asia/Novokuznetsk
 * `Asia/Novosibirsk` - Asia/Novosibirsk
 * `Asia/Omsk` - Asia/Omsk
 * `Asia/Oral` - Asia/Oral
 * `Asia/Phnom_Penh` - Asia/Phnom_Penh
 * `Asia/Pontianak` - Asia/Pontianak
 * `Asia/Pyongyang` - Asia/Pyongyang
 * `Asia/Qatar` - Asia/Qatar
 * `Asia/Qostanay` - Asia/Qostanay
 * `Asia/Qyzylorda` - Asia/Qyzylorda
 * `Asia/Rangoon` - Asia/Rangoon
 * `Asia/Riyadh` - Asia/Riyadh
 * `Asia/Saigon` - Asia/Saigon
 * `Asia/Sakhalin` - Asia/Sakhalin
 * `Asia/Samarkand` - Asia/Samarkand
 * `Asia/Seoul` - Asia/Seoul
 * `Asia/Shanghai` - Asia/Shanghai
 * `Asia/Singapore` - Asia/Singapore
 * `Asia/Srednekolymsk` - Asia/Srednekolymsk
 * `Asia/Taipei` - Asia/Taipei
 * `Asia/Tashkent` - Asia/Tashkent
 * `Asia/Tbilisi` - Asia/Tbilisi
 * `Asia/Tehran` - Asia/Tehran
 * `Asia/Tel_Aviv` - Asia/Tel_Aviv
 * `Asia/Thimbu` - Asia/Thimbu
 * `Asia/Thimphu` - Asia/Thimphu
 * `Asia/Tokyo` - Asia/Tokyo
 * `Asia/Tomsk` - Asia/Tomsk
 * `Asia/Ujung_Pandang` - Asia/Ujung_Pandang
 * `Asia/Ulaanbaatar` - Asia/Ulaanbaatar
 * `Asia/Ulan_Bator` - Asia/Ulan_Bator
 * `Asia/Urumqi` - Asia/Urumqi
 * `Asia/Ust-Nera` - Asia/Ust-Nera
 * `Asia/Vientiane` - Asia/Vientiane
 * `Asia/Vladivostok` - Asia/Vladivostok
 * `Asia/Yakutsk` - Asia/Yakutsk
 * `Asia/Yangon` - Asia/Yangon
 * `Asia/Yekaterinburg` - Asia/Yekaterinburg
 * `Asia/Yerevan` - Asia/Yerevan
 * `Atlantic/Azores` - Atlantic/Azores
 * `Atlantic/Bermuda` - Atlantic/Bermuda
 * `Atlantic/Canary` - Atlantic/Canary
 * `Atlantic/Cape_Verde` - Atlantic/Cape_Verde
 * `Atlantic/Faeroe` - Atlantic/Faeroe
 * `Atlantic/Faroe` - Atlantic/Faroe
 * `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen
 * `Atlantic/Madeira` - Atlantic/Madeira
 * `Atlantic/Reykjavik` - Atlantic/Reykjavik
 * `Atlantic/South_Georgia` - Atlantic/South_Georgia
 * `Atlantic/St_Helena` - Atlantic/St_Helena
 * `Atlantic/Stanley` - Atlantic/Stanley
 * `Australia/ACT` - Australia/ACT
 * `Australia/Adelaide` - Australia/Adelaide
 * `Australia/Brisbane` - Australia/Brisbane
 * `Australia/Broken_Hill` - Australia/Broken_Hill
 * `Australia/Canberra` - Australia/Canberra
 * `Australia/Currie` - Australia/Currie
 * `Australia/Darwin` - Australia/Darwin
 * `Australia/Eucla` - Australia/Eucla
 * `Australia/Hobart` - Australia/Hobart
 * `Australia/LHI` - Australia/LHI
 * `Australia/Lindeman` - Australia/Lindeman
 * `Australia/Lord_Howe` - Australia/Lord_Howe
 * `Australia/Melbourne` - Australia/Melbourne
 * `Australia/NSW` - Australia/NSW
 * `Australia/North` - Australia/North
 * `Australia/Perth` - Australia/Perth
 * `Australia/Queensland` - Australia/Queensland
 * `Australia/South` - Australia/South
 * `Australia/Sydney` - Australia/Sydney
 * `Australia/Tasmania` - Australia/Tasmania
 * `Australia/Victoria` - Australia/Victoria
 * `Australia/West` - Australia/West
 * `Australia/Yancowinna` - Australia/Yancowinna
 * `Brazil/Acre` - Brazil/Acre
 * `Brazil/DeNoronha` - Brazil/DeNoronha
 * `Brazil/East` - Brazil/East
 * `Brazil/West` - Brazil/West
 * `CET` - CET
 * `CST6CDT` - CST6CDT
 * `Canada/Atlantic` - Canada/Atlantic
 * `Canada/Central` - Canada/Central
 * `Canada/Eastern` - Canada/Eastern
 * `Canada/Mountain` - Canada/Mountain
 * `Canada/Newfoundland` - Canada/Newfoundland
 * `Canada/Pacific` - Canada/Pacific
 * `Canada/Saskatchewan` - Canada/Saskatchewan
 * `Canada/Yukon` - Canada/Yukon
 * `Chile/Continental` - Chile/Continental
 * `Chile/EasterIsland` - Chile/EasterIsland
 * `Cuba` - Cuba
 * `EET` - EET
 * `EST` - EST
 * `EST5EDT` - EST5EDT
 * `Egypt` - Egypt
 * `Eire` - Eire
 * `Etc/GMT` - Etc/GMT
 * `Etc/GMT+0` - Etc/GMT+0
 * `Etc/GMT+1` - Etc/GMT+1
 * `Etc/GMT+10` - Etc/GMT+10
 * `Etc/GMT+11` - Etc/GMT+11
 * `Etc/GMT+12` - Etc/GMT+12
 * `Etc/GMT+2` - Etc/GMT+2
 * `Etc/GMT+3` - Etc/GMT+3
 * `Etc/GMT+4` - Etc/GMT+4
 * `Etc/GMT+5` - Etc/GMT+5
 * `Etc/GMT+6` - Etc/GMT+6
 * `Etc/GMT+7` - Etc/GMT+7
 * `Etc/GMT+8` - Etc/GMT+8
 * `Etc/GMT+9` - Etc/GMT+9
 * `Etc/GMT-0` - Etc/GMT-0
 * `Etc/GMT-1` - Etc/GMT-1
 * `Etc/GMT-10` - Etc/GMT-10
 * `Etc/GMT-11` - Etc/GMT-11
 * `Etc/GMT-12` - Etc/GMT-12
 * `Etc/GMT-13` - Etc/GMT-13
 * `Etc/GMT-14` - Etc/GMT-14
 * `Etc/GMT-2` - Etc/GMT-2
 * `Etc/GMT-3` - Etc/GMT-3
 * `Etc/GMT-4` - Etc/GMT-4
 * `Etc/GMT-5` - Etc/GMT-5
 * `Etc/GMT-6` - Etc/GMT-6
 * `Etc/GMT-7` - Etc/GMT-7
 * `Etc/GMT-8` - Etc/GMT-8
 * `Etc/GMT-9` - Etc/GMT-9
 * `Etc/GMT0` - Etc/GMT0
 * `Etc/Greenwich` - Etc/Greenwich
 * `Etc/UCT` - Etc/UCT
 * `Etc/UTC` - Etc/UTC
 * `Etc/Universal` - Etc/Universal
 * `Etc/Zulu` - Etc/Zulu
 * `Europe/Amsterdam` - Europe/Amsterdam
 * `Europe/Andorra` - Europe/Andorra
 * `Europe/Astrakhan` - Europe/Astrakhan
 * `Europe/Athens` - Europe/Athens
 * `Europe/Belfast` - Europe/Belfast
 * `Europe/Belgrade` - Europe/Belgrade
 * `Europe/Berlin` - Europe/Berlin
 * `Europe/Bratislava` - Europe/Bratislava
 * `Europe/Brussels` - Europe/Brussels
 * `Europe/Bucharest` - Europe/Bucharest
 * `Europe/Budapest` - Europe/Budapest
 * `Europe/Busingen` - Europe/Busingen
 * `Europe/Chisinau` - Europe/Chisinau
 * `Europe/Copenhagen` - Europe/Copenhagen
 * `Europe/Dublin` - Europe/Dublin
 * `Europe/Gibraltar` - Europe/Gibraltar
 * `Europe/Guernsey` - Europe/Guernsey
 * `Europe/Helsinki` - Europe/Helsinki
 * `Europe/Isle_of_Man` - Europe/Isle_of_Man
 * `Europe/Istanbul` - Europe/Istanbul
 * `Europe/Jersey` - Europe/Jersey
 * `Europe/Kaliningrad` - Europe/Kaliningrad
 * `Europe/Kiev` - Europe/Kiev
 * `Europe/Kirov` - Europe/Kirov
 * `Europe/Kyiv` - Europe/Kyiv
 * `Europe/Lisbon` - Europe/Lisbon
 * `Europe/Ljubljana` - Europe/Ljubljana
 * `Europe/London` - Europe/London
 * `Europe/Luxembourg` - Europe/Luxembourg
 * `Europe/Madrid` - Europe/Madrid
 * `Europe/Malta` - Europe/Malta
 * `Europe/Mariehamn` - Europe/Mariehamn
 * `Europe/Minsk` - Europe/Minsk
 * `Europe/Monaco` - Europe/Monaco
 * `Europe/Moscow` - Europe/Moscow
 * `Europe/Nicosia` - Europe/Nicosia
 * `Europe/Oslo` - Europe/Oslo
 * `Europe/Paris` - Europe/Paris
 * `Europe/Podgorica` - Europe/Podgorica
 * `Europe/Prague` - Europe/Prague
 * `Europe/Riga` - Europe/Riga
 * `Europe/Rome` - Europe/Rome
 * `Europe/Samara` - Europe/Samara
 * `Europe/San_Marino` - Europe/San_Marino
 * `Europe/Sarajevo` - Europe/Sarajevo
 * `Europe/Saratov` - Europe/Saratov
 * `Europe/Simferopol` - Europe/Simferopol
 * `Europe/Skopje` - Europe/Skopje
 * `Europe/Sofia` - Europe/Sofia
 * `Europe/Stockholm` - Europe/Stockholm
 * `Europe/Tallinn` - Europe/Tallinn
 * `Europe/Tirane` - Europe/Tirane
 * `Europe/Tiraspol` - Europe/Tiraspol
 * `Europe/Ulyanovsk` - Europe/Ulyanovsk
 * `Europe/Uzhgorod` - Europe/Uzhgorod
 * `Europe/Vaduz` - Europe/Vaduz
 * `Europe/Vatican` - Europe/Vatican
 * `Europe/Vienna` - Europe/Vienna
 * `Europe/Vilnius` - Europe/Vilnius
 * `Europe/Volgograd` - Europe/Volgograd
 * `Europe/Warsaw` - Europe/Warsaw
 * `Europe/Zagreb` - Europe/Zagreb
 * `Europe/Zaporozhye` - Europe/Zaporozhye
 * `Europe/Zurich` - Europe/Zurich
 * `GB` - GB
 * `GB-Eire` - GB-Eire
 * `GMT` - GMT
 * `GMT+0` - GMT+0
 * `GMT-0` - GMT-0
 * `GMT0` - GMT0
 * `Greenwich` - Greenwich
 * `HST` - HST
 * `Hongkong` - Hongkong
 * `Iceland` - Iceland
 * `Indian/Antananarivo` - Indian/Antananarivo
 * `Indian/Chagos` - Indian/Chagos
 * `Indian/Christmas` - Indian/Christmas
 * `Indian/Cocos` - Indian/Cocos
 * `Indian/Comoro` - Indian/Comoro
 * `Indian/Kerguelen` - Indian/Kerguelen
 * `Indian/Mahe` - Indian/Mahe
 * `Indian/Maldives` - Indian/Maldives
 * `Indian/Mauritius` - Indian/Mauritius
 * `Indian/Mayotte` - Indian/Mayotte
 * `Indian/Reunion` - Indian/Reunion
 * `Iran` - Iran
 * `Israel` - Israel
 * `Jamaica` - Jamaica
 * `Japan` - Japan
 * `Kwajalein` - Kwajalein
 * `Libya` - Libya
 * `MET` - MET
 * `MST` - MST
 * `MST7MDT` - MST7MDT
 * `Mexico/BajaNorte` - Mexico/BajaNorte
 * `Mexico/BajaSur` - Mexico/BajaSur
 * `Mexico/General` - Mexico/General
 * `NZ` - NZ
 * `NZ-CHAT` - NZ-CHAT
 * `Navajo` - Navajo
 * `PRC` - PRC
 * `PST8PDT` - PST8PDT
 * `Pacific/Apia` - Pacific/Apia
 * `Pacific/Auckland` - Pacific/Auckland
 * `Pacific/Bougainville` - Pacific/Bougainville
 * `Pacific/Chatham` - Pacific/Chatham
 * `Pacific/Chuuk` - Pacific/Chuuk
 * `Pacific/Easter` - Pacific/Easter
 * `Pacific/Efate` - Pacific/Efate
 * `Pacific/Enderbury` - Pacific/Enderbury
 * `Pacific/Fakaofo` - Pacific/Fakaofo
 * `Pacific/Fiji` - Pacific/Fiji
 * `Pacific/Funafuti` - Pacific/Funafuti
 * `Pacific/Galapagos` - Pacific/Galapagos
 * `Pacific/Gambier` - Pacific/Gambier
 * `Pacific/Guadalcanal` - Pacific/Guadalcanal
 * `Pacific/Guam` - Pacific/Guam
 * `Pacific/Honolulu` - Pacific/Honolulu
 * `Pacific/Johnston` - Pacific/Johnston
 * `Pacific/Kanton` - Pacific/Kanton
 * `Pacific/Kiritimati` - Pacific/Kiritimati
 * `Pacific/Kosrae` - Pacific/Kosrae
 * `Pacific/Kwajalein` - Pacific/Kwajalein
 * `Pacific/Majuro` - Pacific/Majuro
 * `Pacific/Marquesas` - Pacific/Marquesas
 * `Pacific/Midway` - Pacific/Midway
 * `Pacific/Nauru` - Pacific/Nauru
 * `Pacific/Niue` - Pacific/Niue
 * `Pacific/Norfolk` - Pacific/Norfolk
 * `Pacific/Noumea` - Pacific/Noumea
 * `Pacific/Pago_Pago` - Pacific/Pago_Pago
 * `Pacific/Palau` - Pacific/Palau
 * `Pacific/Pitcairn` - Pacific/Pitcairn
 * `Pacific/Pohnpei` - Pacific/Pohnpei
 * `Pacific/Ponape` - Pacific/Ponape
 * `Pacific/Port_Moresby` - Pacific/Port_Moresby
 * `Pacific/Rarotonga` - Pacific/Rarotonga
 * `Pacific/Saipan` - Pacific/Saipan
 * `Pacific/Samoa` - Pacific/Samoa
 * `Pacific/Tahiti` - Pacific/Tahiti
 * `Pacific/Tarawa` - Pacific/Tarawa
 * `Pacific/Tongatapu` - Pacific/Tongatapu
 * `Pacific/Truk` - Pacific/Truk
 * `Pacific/Wake` - Pacific/Wake
 * `Pacific/Wallis` - Pacific/Wallis
 * `Pacific/Yap` - Pacific/Yap
 * `Poland` - Poland
 * `Portugal` - Portugal
 * `ROC` - ROC
 * `ROK` - ROK
 * `Singapore` - Singapore
 * `Turkey` - Turkey
 * `UCT` - UCT
 * `US/Alaska` - US/Alaska
 * `US/Aleutian` - US/Aleutian
 * `US/Arizona` - US/Arizona
 * `US/Central` - US/Central
 * `US/East-Indiana` - US/East-Indiana
 * `US/Eastern` - US/Eastern
 * `US/Hawaii` - US/Hawaii
 * `US/Indiana-Starke` - US/Indiana-Starke
 * `US/Michigan` - US/Michigan
 * `US/Mountain` - US/Mountain
 * `US/Pacific` - US/Pacific
 * `US/Samoa` - US/Samoa
 * `UTC` - UTC
 * `Universal` - Universal
 * `W-SU` - W-SU
 * `WET` - WET
 * `Zulu` - Zulu
 */
export type TimezoneEnumApi = (typeof TimezoneEnumApi)[keyof typeof TimezoneEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const TimezoneEnumApi = {
    'Africa/Abidjan': 'Africa/Abidjan',
    'Africa/Accra': 'Africa/Accra',
    'Africa/Addis_Ababa': 'Africa/Addis_Ababa',
    'Africa/Algiers': 'Africa/Algiers',
    'Africa/Asmara': 'Africa/Asmara',
    'Africa/Asmera': 'Africa/Asmera',
    'Africa/Bamako': 'Africa/Bamako',
    'Africa/Bangui': 'Africa/Bangui',
    'Africa/Banjul': 'Africa/Banjul',
    'Africa/Bissau': 'Africa/Bissau',
    'Africa/Blantyre': 'Africa/Blantyre',
    'Africa/Brazzaville': 'Africa/Brazzaville',
    'Africa/Bujumbura': 'Africa/Bujumbura',
    'Africa/Cairo': 'Africa/Cairo',
    'Africa/Casablanca': 'Africa/Casablanca',
    'Africa/Ceuta': 'Africa/Ceuta',
    'Africa/Conakry': 'Africa/Conakry',
    'Africa/Dakar': 'Africa/Dakar',
    'Africa/Dar_es_Salaam': 'Africa/Dar_es_Salaam',
    'Africa/Djibouti': 'Africa/Djibouti',
    'Africa/Douala': 'Africa/Douala',
    'Africa/El_Aaiun': 'Africa/El_Aaiun',
    'Africa/Freetown': 'Africa/Freetown',
    'Africa/Gaborone': 'Africa/Gaborone',
    'Africa/Harare': 'Africa/Harare',
    'Africa/Johannesburg': 'Africa/Johannesburg',
    'Africa/Juba': 'Africa/Juba',
    'Africa/Kampala': 'Africa/Kampala',
    'Africa/Khartoum': 'Africa/Khartoum',
    'Africa/Kigali': 'Africa/Kigali',
    'Africa/Kinshasa': 'Africa/Kinshasa',
    'Africa/Lagos': 'Africa/Lagos',
    'Africa/Libreville': 'Africa/Libreville',
    'Africa/Lome': 'Africa/Lome',
    'Africa/Luanda': 'Africa/Luanda',
    'Africa/Lubumbashi': 'Africa/Lubumbashi',
    'Africa/Lusaka': 'Africa/Lusaka',
    'Africa/Malabo': 'Africa/Malabo',
    'Africa/Maputo': 'Africa/Maputo',
    'Africa/Maseru': 'Africa/Maseru',
    'Africa/Mbabane': 'Africa/Mbabane',
    'Africa/Mogadishu': 'Africa/Mogadishu',
    'Africa/Monrovia': 'Africa/Monrovia',
    'Africa/Nairobi': 'Africa/Nairobi',
    'Africa/Ndjamena': 'Africa/Ndjamena',
    'Africa/Niamey': 'Africa/Niamey',
    'Africa/Nouakchott': 'Africa/Nouakchott',
    'Africa/Ouagadougou': 'Africa/Ouagadougou',
    'Africa/Porto-Novo': 'Africa/Porto-Novo',
    'Africa/Sao_Tome': 'Africa/Sao_Tome',
    'Africa/Timbuktu': 'Africa/Timbuktu',
    'Africa/Tripoli': 'Africa/Tripoli',
    'Africa/Tunis': 'Africa/Tunis',
    'Africa/Windhoek': 'Africa/Windhoek',
    'America/Adak': 'America/Adak',
    'America/Anchorage': 'America/Anchorage',
    'America/Anguilla': 'America/Anguilla',
    'America/Antigua': 'America/Antigua',
    'America/Araguaina': 'America/Araguaina',
    'America/Argentina/Buenos_Aires': 'America/Argentina/Buenos_Aires',
    'America/Argentina/Catamarca': 'America/Argentina/Catamarca',
    'America/Argentina/ComodRivadavia': 'America/Argentina/ComodRivadavia',
    'America/Argentina/Cordoba': 'America/Argentina/Cordoba',
    'America/Argentina/Jujuy': 'America/Argentina/Jujuy',
    'America/Argentina/La_Rioja': 'America/Argentina/La_Rioja',
    'America/Argentina/Mendoza': 'America/Argentina/Mendoza',
    'America/Argentina/Rio_Gallegos': 'America/Argentina/Rio_Gallegos',
    'America/Argentina/Salta': 'America/Argentina/Salta',
    'America/Argentina/San_Juan': 'America/Argentina/San_Juan',
    'America/Argentina/San_Luis': 'America/Argentina/San_Luis',
    'America/Argentina/Tucuman': 'America/Argentina/Tucuman',
    'America/Argentina/Ushuaia': 'America/Argentina/Ushuaia',
    'America/Aruba': 'America/Aruba',
    'America/Asuncion': 'America/Asuncion',
    'America/Atikokan': 'America/Atikokan',
    'America/Atka': 'America/Atka',
    'America/Bahia': 'America/Bahia',
    'America/Bahia_Banderas': 'America/Bahia_Banderas',
    'America/Barbados': 'America/Barbados',
    'America/Belem': 'America/Belem',
    'America/Belize': 'America/Belize',
    'America/Blanc-Sablon': 'America/Blanc-Sablon',
    'America/Boa_Vista': 'America/Boa_Vista',
    'America/Bogota': 'America/Bogota',
    'America/Boise': 'America/Boise',
    'America/Buenos_Aires': 'America/Buenos_Aires',
    'America/Cambridge_Bay': 'America/Cambridge_Bay',
    'America/Campo_Grande': 'America/Campo_Grande',
    'America/Cancun': 'America/Cancun',
    'America/Caracas': 'America/Caracas',
    'America/Catamarca': 'America/Catamarca',
    'America/Cayenne': 'America/Cayenne',
    'America/Cayman': 'America/Cayman',
    'America/Chicago': 'America/Chicago',
    'America/Chihuahua': 'America/Chihuahua',
    'America/Ciudad_Juarez': 'America/Ciudad_Juarez',
    'America/Coral_Harbour': 'America/Coral_Harbour',
    'America/Cordoba': 'America/Cordoba',
    'America/Costa_Rica': 'America/Costa_Rica',
    'America/Creston': 'America/Creston',
    'America/Cuiaba': 'America/Cuiaba',
    'America/Curacao': 'America/Curacao',
    'America/Danmarkshavn': 'America/Danmarkshavn',
    'America/Dawson': 'America/Dawson',
    'America/Dawson_Creek': 'America/Dawson_Creek',
    'America/Denver': 'America/Denver',
    'America/Detroit': 'America/Detroit',
    'America/Dominica': 'America/Dominica',
    'America/Edmonton': 'America/Edmonton',
    'America/Eirunepe': 'America/Eirunepe',
    'America/El_Salvador': 'America/El_Salvador',
    'America/Ensenada': 'America/Ensenada',
    'America/Fort_Nelson': 'America/Fort_Nelson',
    'America/Fort_Wayne': 'America/Fort_Wayne',
    'America/Fortaleza': 'America/Fortaleza',
    'America/Glace_Bay': 'America/Glace_Bay',
    'America/Godthab': 'America/Godthab',
    'America/Goose_Bay': 'America/Goose_Bay',
    'America/Grand_Turk': 'America/Grand_Turk',
    'America/Grenada': 'America/Grenada',
    'America/Guadeloupe': 'America/Guadeloupe',
    'America/Guatemala': 'America/Guatemala',
    'America/Guayaquil': 'America/Guayaquil',
    'America/Guyana': 'America/Guyana',
    'America/Halifax': 'America/Halifax',
    'America/Havana': 'America/Havana',
    'America/Hermosillo': 'America/Hermosillo',
    'America/Indiana/Indianapolis': 'America/Indiana/Indianapolis',
    'America/Indiana/Knox': 'America/Indiana/Knox',
    'America/Indiana/Marengo': 'America/Indiana/Marengo',
    'America/Indiana/Petersburg': 'America/Indiana/Petersburg',
    'America/Indiana/Tell_City': 'America/Indiana/Tell_City',
    'America/Indiana/Vevay': 'America/Indiana/Vevay',
    'America/Indiana/Vincennes': 'America/Indiana/Vincennes',
    'America/Indiana/Winamac': 'America/Indiana/Winamac',
    'America/Indianapolis': 'America/Indianapolis',
    'America/Inuvik': 'America/Inuvik',
    'America/Iqaluit': 'America/Iqaluit',
    'America/Jamaica': 'America/Jamaica',
    'America/Jujuy': 'America/Jujuy',
    'America/Juneau': 'America/Juneau',
    'America/Kentucky/Louisville': 'America/Kentucky/Louisville',
    'America/Kentucky/Monticello': 'America/Kentucky/Monticello',
    'America/Knox_IN': 'America/Knox_IN',
    'America/Kralendijk': 'America/Kralendijk',
    'America/La_Paz': 'America/La_Paz',
    'America/Lima': 'America/Lima',
    'America/Los_Angeles': 'America/Los_Angeles',
    'America/Louisville': 'America/Louisville',
    'America/Lower_Princes': 'America/Lower_Princes',
    'America/Maceio': 'America/Maceio',
    'America/Managua': 'America/Managua',
    'America/Manaus': 'America/Manaus',
    'America/Marigot': 'America/Marigot',
    'America/Martinique': 'America/Martinique',
    'America/Matamoros': 'America/Matamoros',
    'America/Mazatlan': 'America/Mazatlan',
    'America/Mendoza': 'America/Mendoza',
    'America/Menominee': 'America/Menominee',
    'America/Merida': 'America/Merida',
    'America/Metlakatla': 'America/Metlakatla',
    'America/Mexico_City': 'America/Mexico_City',
    'America/Miquelon': 'America/Miquelon',
    'America/Moncton': 'America/Moncton',
    'America/Monterrey': 'America/Monterrey',
    'America/Montevideo': 'America/Montevideo',
    'America/Montreal': 'America/Montreal',
    'America/Montserrat': 'America/Montserrat',
    'America/Nassau': 'America/Nassau',
    'America/New_York': 'America/New_York',
    'America/Nipigon': 'America/Nipigon',
    'America/Nome': 'America/Nome',
    'America/Noronha': 'America/Noronha',
    'America/North_Dakota/Beulah': 'America/North_Dakota/Beulah',
    'America/North_Dakota/Center': 'America/North_Dakota/Center',
    'America/North_Dakota/New_Salem': 'America/North_Dakota/New_Salem',
    'America/Nuuk': 'America/Nuuk',
    'America/Ojinaga': 'America/Ojinaga',
    'America/Panama': 'America/Panama',
    'America/Pangnirtung': 'America/Pangnirtung',
    'America/Paramaribo': 'America/Paramaribo',
    'America/Phoenix': 'America/Phoenix',
    'America/Port-au-Prince': 'America/Port-au-Prince',
    'America/Port_of_Spain': 'America/Port_of_Spain',
    'America/Porto_Acre': 'America/Porto_Acre',
    'America/Porto_Velho': 'America/Porto_Velho',
    'America/Puerto_Rico': 'America/Puerto_Rico',
    'America/Punta_Arenas': 'America/Punta_Arenas',
    'America/Rainy_River': 'America/Rainy_River',
    'America/Rankin_Inlet': 'America/Rankin_Inlet',
    'America/Recife': 'America/Recife',
    'America/Regina': 'America/Regina',
    'America/Resolute': 'America/Resolute',
    'America/Rio_Branco': 'America/Rio_Branco',
    'America/Rosario': 'America/Rosario',
    'America/Santa_Isabel': 'America/Santa_Isabel',
    'America/Santarem': 'America/Santarem',
    'America/Santiago': 'America/Santiago',
    'America/Santo_Domingo': 'America/Santo_Domingo',
    'America/Sao_Paulo': 'America/Sao_Paulo',
    'America/Scoresbysund': 'America/Scoresbysund',
    'America/Shiprock': 'America/Shiprock',
    'America/Sitka': 'America/Sitka',
    'America/St_Barthelemy': 'America/St_Barthelemy',
    'America/St_Johns': 'America/St_Johns',
    'America/St_Kitts': 'America/St_Kitts',
    'America/St_Lucia': 'America/St_Lucia',
    'America/St_Thomas': 'America/St_Thomas',
    'America/St_Vincent': 'America/St_Vincent',
    'America/Swift_Current': 'America/Swift_Current',
    'America/Tegucigalpa': 'America/Tegucigalpa',
    'America/Thule': 'America/Thule',
    'America/Thunder_Bay': 'America/Thunder_Bay',
    'America/Tijuana': 'America/Tijuana',
    'America/Toronto': 'America/Toronto',
    'America/Tortola': 'America/Tortola',
    'America/Vancouver': 'America/Vancouver',
    'America/Virgin': 'America/Virgin',
    'America/Whitehorse': 'America/Whitehorse',
    'America/Winnipeg': 'America/Winnipeg',
    'America/Yakutat': 'America/Yakutat',
    'America/Yellowknife': 'America/Yellowknife',
    'Antarctica/Casey': 'Antarctica/Casey',
    'Antarctica/Davis': 'Antarctica/Davis',
    'Antarctica/DumontDUrville': 'Antarctica/DumontDUrville',
    'Antarctica/Macquarie': 'Antarctica/Macquarie',
    'Antarctica/Mawson': 'Antarctica/Mawson',
    'Antarctica/McMurdo': 'Antarctica/McMurdo',
    'Antarctica/Palmer': 'Antarctica/Palmer',
    'Antarctica/Rothera': 'Antarctica/Rothera',
    'Antarctica/South_Pole': 'Antarctica/South_Pole',
    'Antarctica/Syowa': 'Antarctica/Syowa',
    'Antarctica/Troll': 'Antarctica/Troll',
    'Antarctica/Vostok': 'Antarctica/Vostok',
    'Arctic/Longyearbyen': 'Arctic/Longyearbyen',
    'Asia/Aden': 'Asia/Aden',
    'Asia/Almaty': 'Asia/Almaty',
    'Asia/Amman': 'Asia/Amman',
    'Asia/Anadyr': 'Asia/Anadyr',
    'Asia/Aqtau': 'Asia/Aqtau',
    'Asia/Aqtobe': 'Asia/Aqtobe',
    'Asia/Ashgabat': 'Asia/Ashgabat',
    'Asia/Ashkhabad': 'Asia/Ashkhabad',
    'Asia/Atyrau': 'Asia/Atyrau',
    'Asia/Baghdad': 'Asia/Baghdad',
    'Asia/Bahrain': 'Asia/Bahrain',
    'Asia/Baku': 'Asia/Baku',
    'Asia/Bangkok': 'Asia/Bangkok',
    'Asia/Barnaul': 'Asia/Barnaul',
    'Asia/Beirut': 'Asia/Beirut',
    'Asia/Bishkek': 'Asia/Bishkek',
    'Asia/Brunei': 'Asia/Brunei',
    'Asia/Calcutta': 'Asia/Calcutta',
    'Asia/Chita': 'Asia/Chita',
    'Asia/Choibalsan': 'Asia/Choibalsan',
    'Asia/Chongqing': 'Asia/Chongqing',
    'Asia/Chungking': 'Asia/Chungking',
    'Asia/Colombo': 'Asia/Colombo',
    'Asia/Dacca': 'Asia/Dacca',
    'Asia/Damascus': 'Asia/Damascus',
    'Asia/Dhaka': 'Asia/Dhaka',
    'Asia/Dili': 'Asia/Dili',
    'Asia/Dubai': 'Asia/Dubai',
    'Asia/Dushanbe': 'Asia/Dushanbe',
    'Asia/Famagusta': 'Asia/Famagusta',
    'Asia/Gaza': 'Asia/Gaza',
    'Asia/Harbin': 'Asia/Harbin',
    'Asia/Hebron': 'Asia/Hebron',
    'Asia/Ho_Chi_Minh': 'Asia/Ho_Chi_Minh',
    'Asia/Hong_Kong': 'Asia/Hong_Kong',
    'Asia/Hovd': 'Asia/Hovd',
    'Asia/Irkutsk': 'Asia/Irkutsk',
    'Asia/Istanbul': 'Asia/Istanbul',
    'Asia/Jakarta': 'Asia/Jakarta',
    'Asia/Jayapura': 'Asia/Jayapura',
    'Asia/Jerusalem': 'Asia/Jerusalem',
    'Asia/Kabul': 'Asia/Kabul',
    'Asia/Kamchatka': 'Asia/Kamchatka',
    'Asia/Karachi': 'Asia/Karachi',
    'Asia/Kashgar': 'Asia/Kashgar',
    'Asia/Kathmandu': 'Asia/Kathmandu',
    'Asia/Katmandu': 'Asia/Katmandu',
    'Asia/Khandyga': 'Asia/Khandyga',
    'Asia/Kolkata': 'Asia/Kolkata',
    'Asia/Krasnoyarsk': 'Asia/Krasnoyarsk',
    'Asia/Kuala_Lumpur': 'Asia/Kuala_Lumpur',
    'Asia/Kuching': 'Asia/Kuching',
    'Asia/Kuwait': 'Asia/Kuwait',
    'Asia/Macao': 'Asia/Macao',
    'Asia/Macau': 'Asia/Macau',
    'Asia/Magadan': 'Asia/Magadan',
    'Asia/Makassar': 'Asia/Makassar',
    'Asia/Manila': 'Asia/Manila',
    'Asia/Muscat': 'Asia/Muscat',
    'Asia/Nicosia': 'Asia/Nicosia',
    'Asia/Novokuznetsk': 'Asia/Novokuznetsk',
    'Asia/Novosibirsk': 'Asia/Novosibirsk',
    'Asia/Omsk': 'Asia/Omsk',
    'Asia/Oral': 'Asia/Oral',
    'Asia/Phnom_Penh': 'Asia/Phnom_Penh',
    'Asia/Pontianak': 'Asia/Pontianak',
    'Asia/Pyongyang': 'Asia/Pyongyang',
    'Asia/Qatar': 'Asia/Qatar',
    'Asia/Qostanay': 'Asia/Qostanay',
    'Asia/Qyzylorda': 'Asia/Qyzylorda',
    'Asia/Rangoon': 'Asia/Rangoon',
    'Asia/Riyadh': 'Asia/Riyadh',
    'Asia/Saigon': 'Asia/Saigon',
    'Asia/Sakhalin': 'Asia/Sakhalin',
    'Asia/Samarkand': 'Asia/Samarkand',
    'Asia/Seoul': 'Asia/Seoul',
    'Asia/Shanghai': 'Asia/Shanghai',
    'Asia/Singapore': 'Asia/Singapore',
    'Asia/Srednekolymsk': 'Asia/Srednekolymsk',
    'Asia/Taipei': 'Asia/Taipei',
    'Asia/Tashkent': 'Asia/Tashkent',
    'Asia/Tbilisi': 'Asia/Tbilisi',
    'Asia/Tehran': 'Asia/Tehran',
    'Asia/Tel_Aviv': 'Asia/Tel_Aviv',
    'Asia/Thimbu': 'Asia/Thimbu',
    'Asia/Thimphu': 'Asia/Thimphu',
    'Asia/Tokyo': 'Asia/Tokyo',
    'Asia/Tomsk': 'Asia/Tomsk',
    'Asia/Ujung_Pandang': 'Asia/Ujung_Pandang',
    'Asia/Ulaanbaatar': 'Asia/Ulaanbaatar',
    'Asia/Ulan_Bator': 'Asia/Ulan_Bator',
    'Asia/Urumqi': 'Asia/Urumqi',
    'Asia/Ust-Nera': 'Asia/Ust-Nera',
    'Asia/Vientiane': 'Asia/Vientiane',
    'Asia/Vladivostok': 'Asia/Vladivostok',
    'Asia/Yakutsk': 'Asia/Yakutsk',
    'Asia/Yangon': 'Asia/Yangon',
    'Asia/Yekaterinburg': 'Asia/Yekaterinburg',
    'Asia/Yerevan': 'Asia/Yerevan',
    'Atlantic/Azores': 'Atlantic/Azores',
    'Atlantic/Bermuda': 'Atlantic/Bermuda',
    'Atlantic/Canary': 'Atlantic/Canary',
    'Atlantic/Cape_Verde': 'Atlantic/Cape_Verde',
    'Atlantic/Faeroe': 'Atlantic/Faeroe',
    'Atlantic/Faroe': 'Atlantic/Faroe',
    'Atlantic/Jan_Mayen': 'Atlantic/Jan_Mayen',
    'Atlantic/Madeira': 'Atlantic/Madeira',
    'Atlantic/Reykjavik': 'Atlantic/Reykjavik',
    'Atlantic/South_Georgia': 'Atlantic/South_Georgia',
    'Atlantic/St_Helena': 'Atlantic/St_Helena',
    'Atlantic/Stanley': 'Atlantic/Stanley',
    'Australia/ACT': 'Australia/ACT',
    'Australia/Adelaide': 'Australia/Adelaide',
    'Australia/Brisbane': 'Australia/Brisbane',
    'Australia/Broken_Hill': 'Australia/Broken_Hill',
    'Australia/Canberra': 'Australia/Canberra',
    'Australia/Currie': 'Australia/Currie',
    'Australia/Darwin': 'Australia/Darwin',
    'Australia/Eucla': 'Australia/Eucla',
    'Australia/Hobart': 'Australia/Hobart',
    'Australia/LHI': 'Australia/LHI',
    'Australia/Lindeman': 'Australia/Lindeman',
    'Australia/Lord_Howe': 'Australia/Lord_Howe',
    'Australia/Melbourne': 'Australia/Melbourne',
    'Australia/NSW': 'Australia/NSW',
    'Australia/North': 'Australia/North',
    'Australia/Perth': 'Australia/Perth',
    'Australia/Queensland': 'Australia/Queensland',
    'Australia/South': 'Australia/South',
    'Australia/Sydney': 'Australia/Sydney',
    'Australia/Tasmania': 'Australia/Tasmania',
    'Australia/Victoria': 'Australia/Victoria',
    'Australia/West': 'Australia/West',
    'Australia/Yancowinna': 'Australia/Yancowinna',
    'Brazil/Acre': 'Brazil/Acre',
    'Brazil/DeNoronha': 'Brazil/DeNoronha',
    'Brazil/East': 'Brazil/East',
    'Brazil/West': 'Brazil/West',
    CET: 'CET',
    CST6CDT: 'CST6CDT',
    'Canada/Atlantic': 'Canada/Atlantic',
    'Canada/Central': 'Canada/Central',
    'Canada/Eastern': 'Canada/Eastern',
    'Canada/Mountain': 'Canada/Mountain',
    'Canada/Newfoundland': 'Canada/Newfoundland',
    'Canada/Pacific': 'Canada/Pacific',
    'Canada/Saskatchewan': 'Canada/Saskatchewan',
    'Canada/Yukon': 'Canada/Yukon',
    'Chile/Continental': 'Chile/Continental',
    'Chile/EasterIsland': 'Chile/EasterIsland',
    Cuba: 'Cuba',
    EET: 'EET',
    EST: 'EST',
    EST5EDT: 'EST5EDT',
    Egypt: 'Egypt',
    Eire: 'Eire',
    'Etc/GMT': 'Etc/GMT',
    'Etc/GMT+0': 'Etc/GMT+0',
    'Etc/GMT+1': 'Etc/GMT+1',
    'Etc/GMT+10': 'Etc/GMT+10',
    'Etc/GMT+11': 'Etc/GMT+11',
    'Etc/GMT+12': 'Etc/GMT+12',
    'Etc/GMT+2': 'Etc/GMT+2',
    'Etc/GMT+3': 'Etc/GMT+3',
    'Etc/GMT+4': 'Etc/GMT+4',
    'Etc/GMT+5': 'Etc/GMT+5',
    'Etc/GMT+6': 'Etc/GMT+6',
    'Etc/GMT+7': 'Etc/GMT+7',
    'Etc/GMT+8': 'Etc/GMT+8',
    'Etc/GMT+9': 'Etc/GMT+9',
    'Etc/GMT-0': 'Etc/GMT-0',
    'Etc/GMT-1': 'Etc/GMT-1',
    'Etc/GMT-10': 'Etc/GMT-10',
    'Etc/GMT-11': 'Etc/GMT-11',
    'Etc/GMT-12': 'Etc/GMT-12',
    'Etc/GMT-13': 'Etc/GMT-13',
    'Etc/GMT-14': 'Etc/GMT-14',
    'Etc/GMT-2': 'Etc/GMT-2',
    'Etc/GMT-3': 'Etc/GMT-3',
    'Etc/GMT-4': 'Etc/GMT-4',
    'Etc/GMT-5': 'Etc/GMT-5',
    'Etc/GMT-6': 'Etc/GMT-6',
    'Etc/GMT-7': 'Etc/GMT-7',
    'Etc/GMT-8': 'Etc/GMT-8',
    'Etc/GMT-9': 'Etc/GMT-9',
    'Etc/GMT0': 'Etc/GMT0',
    'Etc/Greenwich': 'Etc/Greenwich',
    'Etc/UCT': 'Etc/UCT',
    'Etc/UTC': 'Etc/UTC',
    'Etc/Universal': 'Etc/Universal',
    'Etc/Zulu': 'Etc/Zulu',
    'Europe/Amsterdam': 'Europe/Amsterdam',
    'Europe/Andorra': 'Europe/Andorra',
    'Europe/Astrakhan': 'Europe/Astrakhan',
    'Europe/Athens': 'Europe/Athens',
    'Europe/Belfast': 'Europe/Belfast',
    'Europe/Belgrade': 'Europe/Belgrade',
    'Europe/Berlin': 'Europe/Berlin',
    'Europe/Bratislava': 'Europe/Bratislava',
    'Europe/Brussels': 'Europe/Brussels',
    'Europe/Bucharest': 'Europe/Bucharest',
    'Europe/Budapest': 'Europe/Budapest',
    'Europe/Busingen': 'Europe/Busingen',
    'Europe/Chisinau': 'Europe/Chisinau',
    'Europe/Copenhagen': 'Europe/Copenhagen',
    'Europe/Dublin': 'Europe/Dublin',
    'Europe/Gibraltar': 'Europe/Gibraltar',
    'Europe/Guernsey': 'Europe/Guernsey',
    'Europe/Helsinki': 'Europe/Helsinki',
    'Europe/Isle_of_Man': 'Europe/Isle_of_Man',
    'Europe/Istanbul': 'Europe/Istanbul',
    'Europe/Jersey': 'Europe/Jersey',
    'Europe/Kaliningrad': 'Europe/Kaliningrad',
    'Europe/Kiev': 'Europe/Kiev',
    'Europe/Kirov': 'Europe/Kirov',
    'Europe/Kyiv': 'Europe/Kyiv',
    'Europe/Lisbon': 'Europe/Lisbon',
    'Europe/Ljubljana': 'Europe/Ljubljana',
    'Europe/London': 'Europe/London',
    'Europe/Luxembourg': 'Europe/Luxembourg',
    'Europe/Madrid': 'Europe/Madrid',
    'Europe/Malta': 'Europe/Malta',
    'Europe/Mariehamn': 'Europe/Mariehamn',
    'Europe/Minsk': 'Europe/Minsk',
    'Europe/Monaco': 'Europe/Monaco',
    'Europe/Moscow': 'Europe/Moscow',
    'Europe/Nicosia': 'Europe/Nicosia',
    'Europe/Oslo': 'Europe/Oslo',
    'Europe/Paris': 'Europe/Paris',
    'Europe/Podgorica': 'Europe/Podgorica',
    'Europe/Prague': 'Europe/Prague',
    'Europe/Riga': 'Europe/Riga',
    'Europe/Rome': 'Europe/Rome',
    'Europe/Samara': 'Europe/Samara',
    'Europe/San_Marino': 'Europe/San_Marino',
    'Europe/Sarajevo': 'Europe/Sarajevo',
    'Europe/Saratov': 'Europe/Saratov',
    'Europe/Simferopol': 'Europe/Simferopol',
    'Europe/Skopje': 'Europe/Skopje',
    'Europe/Sofia': 'Europe/Sofia',
    'Europe/Stockholm': 'Europe/Stockholm',
    'Europe/Tallinn': 'Europe/Tallinn',
    'Europe/Tirane': 'Europe/Tirane',
    'Europe/Tiraspol': 'Europe/Tiraspol',
    'Europe/Ulyanovsk': 'Europe/Ulyanovsk',
    'Europe/Uzhgorod': 'Europe/Uzhgorod',
    'Europe/Vaduz': 'Europe/Vaduz',
    'Europe/Vatican': 'Europe/Vatican',
    'Europe/Vienna': 'Europe/Vienna',
    'Europe/Vilnius': 'Europe/Vilnius',
    'Europe/Volgograd': 'Europe/Volgograd',
    'Europe/Warsaw': 'Europe/Warsaw',
    'Europe/Zagreb': 'Europe/Zagreb',
    'Europe/Zaporozhye': 'Europe/Zaporozhye',
    'Europe/Zurich': 'Europe/Zurich',
    GB: 'GB',
    'GB-Eire': 'GB-Eire',
    GMT: 'GMT',
    'GMT+0': 'GMT+0',
    'GMT-0': 'GMT-0',
    GMT0: 'GMT0',
    Greenwich: 'Greenwich',
    HST: 'HST',
    Hongkong: 'Hongkong',
    Iceland: 'Iceland',
    'Indian/Antananarivo': 'Indian/Antananarivo',
    'Indian/Chagos': 'Indian/Chagos',
    'Indian/Christmas': 'Indian/Christmas',
    'Indian/Cocos': 'Indian/Cocos',
    'Indian/Comoro': 'Indian/Comoro',
    'Indian/Kerguelen': 'Indian/Kerguelen',
    'Indian/Mahe': 'Indian/Mahe',
    'Indian/Maldives': 'Indian/Maldives',
    'Indian/Mauritius': 'Indian/Mauritius',
    'Indian/Mayotte': 'Indian/Mayotte',
    'Indian/Reunion': 'Indian/Reunion',
    Iran: 'Iran',
    Israel: 'Israel',
    Jamaica: 'Jamaica',
    Japan: 'Japan',
    Kwajalein: 'Kwajalein',
    Libya: 'Libya',
    MET: 'MET',
    MST: 'MST',
    MST7MDT: 'MST7MDT',
    'Mexico/BajaNorte': 'Mexico/BajaNorte',
    'Mexico/BajaSur': 'Mexico/BajaSur',
    'Mexico/General': 'Mexico/General',
    NZ: 'NZ',
    'NZ-CHAT': 'NZ-CHAT',
    Navajo: 'Navajo',
    PRC: 'PRC',
    PST8PDT: 'PST8PDT',
    'Pacific/Apia': 'Pacific/Apia',
    'Pacific/Auckland': 'Pacific/Auckland',
    'Pacific/Bougainville': 'Pacific/Bougainville',
    'Pacific/Chatham': 'Pacific/Chatham',
    'Pacific/Chuuk': 'Pacific/Chuuk',
    'Pacific/Easter': 'Pacific/Easter',
    'Pacific/Efate': 'Pacific/Efate',
    'Pacific/Enderbury': 'Pacific/Enderbury',
    'Pacific/Fakaofo': 'Pacific/Fakaofo',
    'Pacific/Fiji': 'Pacific/Fiji',
    'Pacific/Funafuti': 'Pacific/Funafuti',
    'Pacific/Galapagos': 'Pacific/Galapagos',
    'Pacific/Gambier': 'Pacific/Gambier',
    'Pacific/Guadalcanal': 'Pacific/Guadalcanal',
    'Pacific/Guam': 'Pacific/Guam',
    'Pacific/Honolulu': 'Pacific/Honolulu',
    'Pacific/Johnston': 'Pacific/Johnston',
    'Pacific/Kanton': 'Pacific/Kanton',
    'Pacific/Kiritimati': 'Pacific/Kiritimati',
    'Pacific/Kosrae': 'Pacific/Kosrae',
    'Pacific/Kwajalein': 'Pacific/Kwajalein',
    'Pacific/Majuro': 'Pacific/Majuro',
    'Pacific/Marquesas': 'Pacific/Marquesas',
    'Pacific/Midway': 'Pacific/Midway',
    'Pacific/Nauru': 'Pacific/Nauru',
    'Pacific/Niue': 'Pacific/Niue',
    'Pacific/Norfolk': 'Pacific/Norfolk',
    'Pacific/Noumea': 'Pacific/Noumea',
    'Pacific/Pago_Pago': 'Pacific/Pago_Pago',
    'Pacific/Palau': 'Pacific/Palau',
    'Pacific/Pitcairn': 'Pacific/Pitcairn',
    'Pacific/Pohnpei': 'Pacific/Pohnpei',
    'Pacific/Ponape': 'Pacific/Ponape',
    'Pacific/Port_Moresby': 'Pacific/Port_Moresby',
    'Pacific/Rarotonga': 'Pacific/Rarotonga',
    'Pacific/Saipan': 'Pacific/Saipan',
    'Pacific/Samoa': 'Pacific/Samoa',
    'Pacific/Tahiti': 'Pacific/Tahiti',
    'Pacific/Tarawa': 'Pacific/Tarawa',
    'Pacific/Tongatapu': 'Pacific/Tongatapu',
    'Pacific/Truk': 'Pacific/Truk',
    'Pacific/Wake': 'Pacific/Wake',
    'Pacific/Wallis': 'Pacific/Wallis',
    'Pacific/Yap': 'Pacific/Yap',
    Poland: 'Poland',
    Portugal: 'Portugal',
    ROC: 'ROC',
    ROK: 'ROK',
    Singapore: 'Singapore',
    Turkey: 'Turkey',
    UCT: 'UCT',
    'US/Alaska': 'US/Alaska',
    'US/Aleutian': 'US/Aleutian',
    'US/Arizona': 'US/Arizona',
    'US/Central': 'US/Central',
    'US/East-Indiana': 'US/East-Indiana',
    'US/Eastern': 'US/Eastern',
    'US/Hawaii': 'US/Hawaii',
    'US/Indiana-Starke': 'US/Indiana-Starke',
    'US/Michigan': 'US/Michigan',
    'US/Mountain': 'US/Mountain',
    'US/Pacific': 'US/Pacific',
    'US/Samoa': 'US/Samoa',
    UTC: 'UTC',
    Universal: 'Universal',
    'W-SU': 'W-SU',
    WET: 'WET',
    Zulu: 'Zulu',
} as const

/**
 * Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of
passthrough fields. This allows the meaning of `Team` to change from "project" to "environment" without breaking
backward compatibility of the REST API.
Do not use this in greenfield endpoints!
 */
export interface ProjectBackwardCompatBasicApi {
    readonly id: number
    readonly uuid: string
    readonly organization: string
    readonly api_token: string
    readonly name: string
    readonly completed_snippet_onboarding: boolean
    readonly has_completed_onboarding_for: unknown
    readonly ingested_event: boolean
    readonly is_demo: boolean
    readonly timezone: TimezoneEnumApi
    readonly access_control: boolean
}

export interface PaginatedProjectBackwardCompatBasicListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ProjectBackwardCompatBasicApi[]
}

export type ProjectBackwardCompatApiGroupTypesItem = { [key: string]: unknown }

export type EffectiveMembershipLevelEnumApi =
    (typeof EffectiveMembershipLevelEnumApi)[keyof typeof EffectiveMembershipLevelEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EffectiveMembershipLevelEnumApi = {
    NUMBER_1: 1,
    NUMBER_8: 8,
    NUMBER_15: 15,
} as const

/**
 * * `0` - Sunday
 * `1` - Monday
 */
export type WeekStartDayEnumApi = (typeof WeekStartDayEnumApi)[keyof typeof WeekStartDayEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const WeekStartDayEnumApi = {
    NUMBER_0: 0,
    NUMBER_1: 1,
} as const

/**
 * * `b2b` - B2B
 * `b2c` - B2C
 * `other` - Other
 */
export type BusinessModelEnumApi = (typeof BusinessModelEnumApi)[keyof typeof BusinessModelEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BusinessModelEnumApi = {
    b2b: 'b2b',
    b2c: 'b2c',
    other: 'other',
} as const

/**
 * Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of
passthrough fields. This allows the meaning of `Team` to change from "project" to "environment" without breaking
backward compatibility of the REST API.
Do not use this in greenfield endpoints!
 */
export interface ProjectBackwardCompatApi {
    readonly id: number
    readonly organization: string
    /**
     * @minLength 1
     * @maxLength 200
     */
    name?: string
    /**
     * @maxLength 1000
     * @nullable
     */
    product_description?: string | null
    readonly created_at: string
    readonly effective_membership_level: EffectiveMembershipLevelEnumApi
    readonly has_group_types: boolean
    readonly group_types: readonly ProjectBackwardCompatApiGroupTypesItem[]
    /** @nullable */
    readonly live_events_token: string | null
    readonly updated_at: string
    readonly uuid: string
    readonly api_token: string
    app_urls?: (string | null)[]
    /**
     * @maxLength 500
     * @nullable
     */
    slack_incoming_webhook?: string | null
    anonymize_ips?: boolean
    completed_snippet_onboarding?: boolean
    readonly ingested_event: boolean
    test_account_filters?: unknown
    /** @nullable */
    test_account_filters_default_checked?: boolean | null
    path_cleaning_filters?: unknown
    is_demo?: boolean
    timezone?: TimezoneEnumApi
    data_attributes?: unknown
    /** @nullable */
    person_display_name_properties?: string[] | null
    correlation_config?: unknown
    /** @nullable */
    autocapture_opt_out?: boolean | null
    /** @nullable */
    autocapture_exceptions_opt_in?: boolean | null
    /** @nullable */
    autocapture_web_vitals_opt_in?: boolean | null
    autocapture_web_vitals_allowed_metrics?: unknown
    autocapture_exceptions_errors_to_ignore?: unknown
    /** @nullable */
    capture_console_log_opt_in?: boolean | null
    /** @nullable */
    capture_performance_opt_in?: boolean | null
    session_recording_opt_in?: boolean
    /**
     * @nullable
     * @pattern ^-?\d{0,1}(?:\.\d{0,2})?$
     */
    session_recording_sample_rate?: string | null
    /**
     * @minimum 0
     * @maximum 30000
     * @nullable
     */
    session_recording_minimum_duration_milliseconds?: number | null
    session_recording_linked_flag?: unknown
    session_recording_network_payload_capture_config?: unknown
    session_recording_masking_config?: unknown
    session_replay_config?: unknown
    survey_config?: unknown
    access_control?: boolean
    /**
     * @minimum -32768
     * @maximum 32767
     */
    week_start_day?: WeekStartDayEnumApi | NullEnumApi
    /** @nullable */
    primary_dashboard?: number | null
    /** @nullable */
    live_events_columns?: string[] | null
    /** @nullable */
    recording_domains?: (string | null)[] | null
    readonly person_on_events_querying_enabled: string
    /** @nullable */
    inject_web_apps?: boolean | null
    extra_settings?: unknown
    modifiers?: unknown
    readonly default_modifiers: string
    has_completed_onboarding_for?: unknown
    /** @nullable */
    surveys_opt_in?: boolean | null
    /** @nullable */
    heatmaps_opt_in?: boolean | null
    readonly product_intents: string
    /** @nullable */
    flags_persistence_default?: boolean | null
    /** @nullable */
    readonly secret_api_token: string | null
    /** @nullable */
    readonly secret_api_token_backup: string | null
    /** @nullable */
    receive_org_level_activity_logs?: boolean | null
    /** Whether this project serves B2B or B2C customers, used to optimize the UI layout.

* `b2b` - B2B
* `b2c` - B2C
* `other` - Other */
    business_model?: BusinessModelEnumApi | BlankEnumApi | NullEnumApi
    /** @nullable */
    conversations_enabled?: boolean | null
    conversations_settings?: unknown
}

export type PatchedProjectBackwardCompatApiGroupTypesItem = { [key: string]: unknown }

/**
 * Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of
passthrough fields. This allows the meaning of `Team` to change from "project" to "environment" without breaking
backward compatibility of the REST API.
Do not use this in greenfield endpoints!
 */
export interface PatchedProjectBackwardCompatApi {
    readonly id?: number
    readonly organization?: string
    /**
     * @minLength 1
     * @maxLength 200
     */
    name?: string
    /**
     * @maxLength 1000
     * @nullable
     */
    product_description?: string | null
    readonly created_at?: string
    readonly effective_membership_level?: EffectiveMembershipLevelEnumApi
    readonly has_group_types?: boolean
    readonly group_types?: readonly PatchedProjectBackwardCompatApiGroupTypesItem[]
    /** @nullable */
    readonly live_events_token?: string | null
    readonly updated_at?: string
    readonly uuid?: string
    readonly api_token?: string
    app_urls?: (string | null)[]
    /**
     * @maxLength 500
     * @nullable
     */
    slack_incoming_webhook?: string | null
    anonymize_ips?: boolean
    completed_snippet_onboarding?: boolean
    readonly ingested_event?: boolean
    test_account_filters?: unknown
    /** @nullable */
    test_account_filters_default_checked?: boolean | null
    path_cleaning_filters?: unknown
    is_demo?: boolean
    timezone?: TimezoneEnumApi
    data_attributes?: unknown
    /** @nullable */
    person_display_name_properties?: string[] | null
    correlation_config?: unknown
    /** @nullable */
    autocapture_opt_out?: boolean | null
    /** @nullable */
    autocapture_exceptions_opt_in?: boolean | null
    /** @nullable */
    autocapture_web_vitals_opt_in?: boolean | null
    autocapture_web_vitals_allowed_metrics?: unknown
    autocapture_exceptions_errors_to_ignore?: unknown
    /** @nullable */
    capture_console_log_opt_in?: boolean | null
    /** @nullable */
    capture_performance_opt_in?: boolean | null
    session_recording_opt_in?: boolean
    /**
     * @nullable
     * @pattern ^-?\d{0,1}(?:\.\d{0,2})?$
     */
    session_recording_sample_rate?: string | null
    /**
     * @minimum 0
     * @maximum 30000
     * @nullable
     */
    session_recording_minimum_duration_milliseconds?: number | null
    session_recording_linked_flag?: unknown
    session_recording_network_payload_capture_config?: unknown
    session_recording_masking_config?: unknown
    session_replay_config?: unknown
    survey_config?: unknown
    access_control?: boolean
    /**
     * @minimum -32768
     * @maximum 32767
     */
    week_start_day?: WeekStartDayEnumApi | NullEnumApi
    /** @nullable */
    primary_dashboard?: number | null
    /** @nullable */
    live_events_columns?: string[] | null
    /** @nullable */
    recording_domains?: (string | null)[] | null
    readonly person_on_events_querying_enabled?: string
    /** @nullable */
    inject_web_apps?: boolean | null
    extra_settings?: unknown
    modifiers?: unknown
    readonly default_modifiers?: string
    has_completed_onboarding_for?: unknown
    /** @nullable */
    surveys_opt_in?: boolean | null
    /** @nullable */
    heatmaps_opt_in?: boolean | null
    readonly product_intents?: string
    /** @nullable */
    flags_persistence_default?: boolean | null
    /** @nullable */
    readonly secret_api_token?: string | null
    /** @nullable */
    readonly secret_api_token_backup?: string | null
    /** @nullable */
    receive_org_level_activity_logs?: boolean | null
    /** Whether this project serves B2B or B2C customers, used to optimize the UI layout.

* `b2b` - B2B
* `b2c` - B2C
* `other` - Other */
    business_model?: BusinessModelEnumApi | BlankEnumApi | NullEnumApi
    /** @nullable */
    conversations_enabled?: boolean | null
    conversations_settings?: unknown
}

export interface RoleApi {
    readonly id: string
    /** @maxLength 200 */
    name: string
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly members: string
    readonly is_default: string
}

export interface PaginatedRoleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: RoleApi[]
}

export interface PatchedRoleApi {
    readonly id?: string
    /** @maxLength 200 */
    name?: string
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly members?: string
    readonly is_default?: string
}

/**
 * * `USR` - user
 * `GIT` - GitHub
 */
export type CreationTypeEnumApi = (typeof CreationTypeEnumApi)[keyof typeof CreationTypeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CreationTypeEnumApi = {
    USR: 'USR',
    GIT: 'GIT',
} as const

/**
 * * `dashboard_item` - insight
 * `dashboard` - dashboard
 * `project` - project
 * `organization` - organization
 * `recording` - recording
 */
export type AnnotationScopeEnumApi = (typeof AnnotationScopeEnumApi)[keyof typeof AnnotationScopeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const AnnotationScopeEnumApi = {
    dashboard_item: 'dashboard_item',
    dashboard: 'dashboard',
    project: 'project',
    organization: 'organization',
    recording: 'recording',
} as const

export interface AnnotationApi {
    readonly id: number
    /**
     * @maxLength 400
     * @nullable
     */
    content?: string | null
    /** @nullable */
    date_marker?: string | null
    creation_type?: CreationTypeEnumApi
    /** @nullable */
    dashboard_item?: number | null
    /** @nullable */
    dashboard_id?: number | null
    /** @nullable */
    readonly dashboard_name: string | null
    /** @nullable */
    readonly insight_short_id: string | null
    /** @nullable */
    readonly insight_name: string | null
    /** @nullable */
    readonly insight_derived_name: string | null
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly created_at: string | null
    readonly updated_at: string
    deleted?: boolean
    scope?: AnnotationScopeEnumApi
}

export interface PaginatedAnnotationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AnnotationApi[]
}

export interface PatchedAnnotationApi {
    readonly id?: number
    /**
     * @maxLength 400
     * @nullable
     */
    content?: string | null
    /** @nullable */
    date_marker?: string | null
    creation_type?: CreationTypeEnumApi
    /** @nullable */
    dashboard_item?: number | null
    /** @nullable */
    dashboard_id?: number | null
    /** @nullable */
    readonly dashboard_name?: string | null
    /** @nullable */
    readonly insight_short_id?: string | null
    /** @nullable */
    readonly insight_name?: string | null
    /** @nullable */
    readonly insight_derived_name?: string | null
    readonly created_by?: UserBasicApi
    /** @nullable */
    readonly created_at?: string | null
    readonly updated_at?: string
    deleted?: boolean
    scope?: AnnotationScopeEnumApi
}

/**
 * * `static` - static
 * `person_property` - person_property
 * `behavioral` - behavioral
 * `realtime` - realtime
 * `analytical` - analytical
 */
export type CohortTypeEnumApi = (typeof CohortTypeEnumApi)[keyof typeof CohortTypeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
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
    filters?: unknown
    query?: unknown
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
    cohort_type?: CohortTypeEnumApi | BlankEnumApi | NullEnumApi
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
    filters?: unknown
    query?: unknown
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
    cohort_type?: CohortTypeEnumApi | BlankEnumApi | NullEnumApi
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

export interface CommentApi {
    readonly id: string
    readonly created_by: UserBasicApi
    /** @nullable */
    deleted?: boolean | null
    mentions?: number[]
    slug?: string
    /** @nullable */
    content?: string | null
    rich_content?: unknown
    readonly version: number
    readonly created_at: string
    /**
     * @maxLength 72
     * @nullable
     */
    item_id?: string | null
    item_context?: unknown
    /** @maxLength 79 */
    scope: string
    /** @nullable */
    source_comment?: string | null
}

export interface PaginatedCommentListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CommentApi[]
}

export interface PatchedCommentApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    deleted?: boolean | null
    mentions?: number[]
    slug?: string
    /** @nullable */
    content?: string | null
    rich_content?: unknown
    readonly version?: number
    readonly created_at?: string
    /**
     * @maxLength 72
     * @nullable
     */
    item_id?: string | null
    item_context?: unknown
    /** @maxLength 79 */
    scope?: string
    /** @nullable */
    source_comment?: string | null
}

/**
 * * `team` - Only team
 * `global` - Global
 * `feature_flag` - Feature Flag
 */
export type DashboardTemplateScopeEnumApi =
    (typeof DashboardTemplateScopeEnumApi)[keyof typeof DashboardTemplateScopeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardTemplateScopeEnumApi = {
    team: 'team',
    global: 'global',
    feature_flag: 'feature_flag',
} as const

export interface DashboardTemplateApi {
    readonly id: string
    /**
     * @maxLength 400
     * @nullable
     */
    template_name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    dashboard_description?: string | null
    dashboard_filters?: unknown
    /** @nullable */
    tags?: string[] | null
    tiles?: unknown
    variables?: unknown
    /** @nullable */
    deleted?: boolean | null
    /** @nullable */
    readonly created_at: string | null
    /** @nullable */
    created_by?: number | null
    /**
     * @maxLength 8201
     * @nullable
     */
    image_url?: string | null
    /** @nullable */
    readonly team_id: number | null
    scope?: DashboardTemplateScopeEnumApi | BlankEnumApi | NullEnumApi
    /** @nullable */
    availability_contexts?: string[] | null
}

export interface PaginatedDashboardTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DashboardTemplateApi[]
}

export interface PatchedDashboardTemplateApi {
    readonly id?: string
    /**
     * @maxLength 400
     * @nullable
     */
    template_name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    dashboard_description?: string | null
    dashboard_filters?: unknown
    /** @nullable */
    tags?: string[] | null
    tiles?: unknown
    variables?: unknown
    /** @nullable */
    deleted?: boolean | null
    /** @nullable */
    readonly created_at?: string | null
    /** @nullable */
    created_by?: number | null
    /**
     * @maxLength 8201
     * @nullable
     */
    image_url?: string | null
    /** @nullable */
    readonly team_id?: number | null
    scope?: DashboardTemplateScopeEnumApi | BlankEnumApi | NullEnumApi
    /** @nullable */
    availability_contexts?: string[] | null
}

/**
 * * `DateTime` - DateTime
 * `String` - String
 * `Numeric` - Numeric
 * `Boolean` - Boolean
 * `Duration` - Duration
 */
export type PropertyType549EnumApi = (typeof PropertyType549EnumApi)[keyof typeof PropertyType549EnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PropertyType549EnumApi = {
    DateTime: 'DateTime',
    String: 'String',
    Numeric: 'Numeric',
    Boolean: 'Boolean',
    Duration: 'Duration',
} as const

/**
 * * `1` - event
 * `2` - person
 * `3` - group
 * `4` - session
 */
export type PropertyDefinitionTypeEnumApi =
    (typeof PropertyDefinitionTypeEnumApi)[keyof typeof PropertyDefinitionTypeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PropertyDefinitionTypeEnumApi = {
    NUMBER_1: 1,
    NUMBER_2: 2,
    NUMBER_3: 3,
    NUMBER_4: 4,
} as const

export interface PropertyDefinitionApi {
    readonly id: string
    readonly name: string
    readonly property_type: PropertyType549EnumApi | NullEnumApi
    readonly type: PropertyDefinitionTypeEnumApi
}

export interface PaginatedPropertyDefinitionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: PropertyDefinitionApi[]
}

/**
 * Serializer mixin that resolves appropriate response for tags depending on license.
 */
export interface PatchedPropertyDefinitionApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    is_numerical?: boolean
    property_type?: PropertyType549EnumApi | BlankEnumApi | NullEnumApi
    tags?: unknown[]
    readonly is_seen_on_filtered_events?: string
}

/**
 * * `FeatureFlag` - feature flag
 */
export type ModelNameEnumApi = (typeof ModelNameEnumApi)[keyof typeof ModelNameEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ModelNameEnumApi = {
    FeatureFlag: 'FeatureFlag',
} as const

/**
 * * `daily` - daily
 * `weekly` - weekly
 * `monthly` - monthly
 * `yearly` - yearly
 */
export type RecurrenceIntervalEnumApi = (typeof RecurrenceIntervalEnumApi)[keyof typeof RecurrenceIntervalEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const RecurrenceIntervalEnumApi = {
    daily: 'daily',
    weekly: 'weekly',
    monthly: 'monthly',
    yearly: 'yearly',
} as const

export interface ScheduledChangeApi {
    readonly id: number
    readonly team_id: number
    /** @maxLength 200 */
    record_id: string
    model_name: ModelNameEnumApi
    payload?: unknown
    scheduled_at: string
    /** @nullable */
    executed_at?: string | null
    /**
     * Return the safely formatted failure reason instead of raw data.
     * @nullable
     */
    readonly failure_reason: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    is_recurring?: boolean
    recurrence_interval?: RecurrenceIntervalEnumApi | BlankEnumApi | NullEnumApi
    /** @nullable */
    readonly last_executed_at: string | null
    /** @nullable */
    end_date?: string | null
}

export interface PaginatedScheduledChangeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ScheduledChangeApi[]
}

export interface PatchedScheduledChangeApi {
    readonly id?: number
    readonly team_id?: number
    /** @maxLength 200 */
    record_id?: string
    model_name?: ModelNameEnumApi
    payload?: unknown
    scheduled_at?: string
    /** @nullable */
    executed_at?: string | null
    /**
     * Return the safely formatted failure reason instead of raw data.
     * @nullable
     */
    readonly failure_reason?: string | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly updated_at?: string
    is_recurring?: boolean
    recurrence_interval?: RecurrenceIntervalEnumApi | BlankEnumApi | NullEnumApi
    /** @nullable */
    readonly last_executed_at?: string | null
    /** @nullable */
    end_date?: string | null
}

/**
 * * `disabled` - disabled
 * `toolbar` - toolbar
 */
export type ToolbarModeEnumApi = (typeof ToolbarModeEnumApi)[keyof typeof ToolbarModeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ToolbarModeEnumApi = {
    disabled: 'disabled',
    toolbar: 'toolbar',
} as const

/**
 * Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.
Also used for nested serializers.
 */
export interface TeamBasicApi {
    readonly id: number
    readonly uuid: string
    readonly organization: string
    /**
     * @minimum -9223372036854776000
     * @maximum 9223372036854776000
     */
    readonly project_id: number
    readonly api_token: string
    readonly name: string
    readonly completed_snippet_onboarding: boolean
    readonly has_completed_onboarding_for: unknown
    readonly ingested_event: boolean
    readonly is_demo: boolean
    readonly timezone: TimezoneEnumApi
    readonly access_control: boolean
}

export type MembershipLevelEnumApi = (typeof MembershipLevelEnumApi)[keyof typeof MembershipLevelEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const MembershipLevelEnumApi = {
    NUMBER_1: 1,
    NUMBER_8: 8,
    NUMBER_15: 15,
} as const

/**
 * * `0` - none
 * `3` - config
 * `6` - install
 * `9` - root
 */
export type PluginsAccessLevelEnumApi = (typeof PluginsAccessLevelEnumApi)[keyof typeof PluginsAccessLevelEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PluginsAccessLevelEnumApi = {
    NUMBER_0: 0,
    NUMBER_3: 3,
    NUMBER_6: 6,
    NUMBER_9: 9,
} as const

/**
 * * `bayesian` - Bayesian
 * `frequentist` - Frequentist
 */
export type DefaultExperimentStatsMethodEnumApi =
    (typeof DefaultExperimentStatsMethodEnumApi)[keyof typeof DefaultExperimentStatsMethodEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DefaultExperimentStatsMethodEnumApi = {
    bayesian: 'bayesian',
    frequentist: 'frequentist',
} as const

export type OrganizationApiTeamsItem = { [key: string]: unknown }

export type OrganizationApiProjectsItem = { [key: string]: unknown }

export interface OrganizationApi {
    readonly id: string
    /** @maxLength 64 */
    name: string
    /** @pattern ^[-a-zA-Z0-9_]+$ */
    readonly slug: string
    /** @nullable */
    logo_media_id?: string | null
    readonly created_at: string
    readonly updated_at: string
    readonly membership_level: MembershipLevelEnumApi
    readonly plugins_access_level: PluginsAccessLevelEnumApi
    readonly teams: readonly OrganizationApiTeamsItem[]
    readonly projects: readonly OrganizationApiProjectsItem[]
    /** @nullable */
    readonly available_product_features: readonly unknown[] | null
    is_member_join_email_enabled?: boolean
    readonly metadata: string
    /** @nullable */
    readonly customer_id: string | null
    /** @nullable */
    enforce_2fa?: boolean | null
    /** @nullable */
    members_can_invite?: boolean | null
    members_can_use_personal_api_keys?: boolean
    allow_publicly_shared_resources?: boolean
    readonly member_count: string
    /** @nullable */
    is_ai_data_processing_approved?: boolean | null
    /** Default statistical method for new experiments in this organization.

* `bayesian` - Bayesian
* `frequentist` - Frequentist */
    default_experiment_stats_method?: DefaultExperimentStatsMethodEnumApi | BlankEnumApi | NullEnumApi
    /** Default setting for 'Discard client IP data' for new projects in this organization. */
    default_anonymize_ips?: boolean
    /**
     * ID of the role to automatically assign to new members joining the organization
     * @nullable
     */
    default_role_id?: string | null
    /**
     * Set this to 'No' to temporarily disable an organization.
     * @nullable
     */
    readonly is_active: boolean | null
    /**
     * (optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.
     * @nullable
     */
    readonly is_not_active_reason: string | null
}

/**
 * Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
Also used for nested serializers.
 */
export interface OrganizationBasicApi {
    readonly id: string
    /** @maxLength 64 */
    name: string
    /**
     * @maxLength 48
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug: string
    /** @nullable */
    readonly logo_media_id: string | null
    readonly membership_level: MembershipLevelEnumApi
    members_can_use_personal_api_keys?: boolean
    /**
     * Set this to 'No' to temporarily disable an organization.
     * @nullable
     */
    is_active?: boolean | null
    /**
     * (optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.
     * @maxLength 200
     * @nullable
     */
    is_not_active_reason?: string | null
}

export interface ScenePersonalisationBasicApi {
    /** @maxLength 200 */
    scene: string
    /** @nullable */
    dashboard?: number | null
}

/**
 * * `light` - Light
 * `dark` - Dark
 * `system` - System
 */
export type ThemeModeEnumApi = (typeof ThemeModeEnumApi)[keyof typeof ThemeModeEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ThemeModeEnumApi = {
    light: 'light',
    dark: 'dark',
    system: 'system',
} as const

/**
 * * `above` - Above
 * `below` - Below
 * `hidden` - Hidden
 */
export type ShortcutPositionEnumApi = (typeof ShortcutPositionEnumApi)[keyof typeof ShortcutPositionEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ShortcutPositionEnumApi = {
    above: 'above',
    below: 'below',
    hidden: 'hidden',
} as const

export type UserApiNotificationSettings = { [key: string]: unknown }

export interface UserApi {
    readonly date_joined: string
    readonly uuid: string
    /** @nullable */
    readonly distinct_id: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    readonly pending_email: string | null
    /** @nullable */
    readonly is_email_verified: boolean | null
    notification_settings?: UserApiNotificationSettings
    /** @nullable */
    anonymize_data?: boolean | null
    /** @nullable */
    allow_impersonation?: boolean | null
    toolbar_mode?: ToolbarModeEnumApi | BlankEnumApi | NullEnumApi
    readonly has_password: boolean
    readonly id: number
    /** Designates whether the user can log into this admin site. */
    is_staff?: boolean
    /** @nullable */
    readonly is_impersonated: boolean | null
    /** @nullable */
    readonly is_impersonated_until: string | null
    /** @nullable */
    readonly is_impersonated_read_only: boolean | null
    /** @nullable */
    readonly sensitive_session_expires_at: string | null
    readonly team: TeamBasicApi
    readonly organization: OrganizationApi
    readonly organizations: readonly OrganizationBasicApi[]
    set_current_organization?: string
    set_current_team?: string
    /** @maxLength 128 */
    password: string
    current_password?: string
    events_column_config?: unknown
    readonly is_2fa_enabled: boolean
    readonly has_social_auth: boolean
    readonly has_sso_enforcement: boolean
    has_seen_product_intro_for?: unknown
    readonly scene_personalisation: readonly ScenePersonalisationBasicApi[]
    theme_mode?: ThemeModeEnumApi | BlankEnumApi | NullEnumApi
    hedgehog_config?: unknown
    /** @nullable */
    allow_sidebar_suggestions?: boolean | null
    shortcut_position?: ShortcutPositionEnumApi | BlankEnumApi | NullEnumApi
    role_at_organization?: RoleAtOrganizationEnumApi
}

export interface PaginatedUserListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UserApi[]
}

export type PatchedUserApiNotificationSettings = { [key: string]: unknown }

export interface PatchedUserApi {
    readonly date_joined?: string
    readonly uuid?: string
    /** @nullable */
    readonly distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email?: string
    /** @nullable */
    readonly pending_email?: string | null
    /** @nullable */
    readonly is_email_verified?: boolean | null
    notification_settings?: PatchedUserApiNotificationSettings
    /** @nullable */
    anonymize_data?: boolean | null
    /** @nullable */
    allow_impersonation?: boolean | null
    toolbar_mode?: ToolbarModeEnumApi | BlankEnumApi | NullEnumApi
    readonly has_password?: boolean
    readonly id?: number
    /** Designates whether the user can log into this admin site. */
    is_staff?: boolean
    /** @nullable */
    readonly is_impersonated?: boolean | null
    /** @nullable */
    readonly is_impersonated_until?: string | null
    /** @nullable */
    readonly is_impersonated_read_only?: boolean | null
    /** @nullable */
    readonly sensitive_session_expires_at?: string | null
    readonly team?: TeamBasicApi
    readonly organization?: OrganizationApi
    readonly organizations?: readonly OrganizationBasicApi[]
    set_current_organization?: string
    set_current_team?: string
    /** @maxLength 128 */
    password?: string
    current_password?: string
    events_column_config?: unknown
    readonly is_2fa_enabled?: boolean
    readonly has_social_auth?: boolean
    readonly has_sso_enforcement?: boolean
    has_seen_product_intro_for?: unknown
    readonly scene_personalisation?: readonly ScenePersonalisationBasicApi[]
    theme_mode?: ThemeModeEnumApi | BlankEnumApi | NullEnumApi
    hedgehog_config?: unknown
    /** @nullable */
    allow_sidebar_suggestions?: boolean | null
    shortcut_position?: ShortcutPositionEnumApi | BlankEnumApi | NullEnumApi
    role_at_organization?: RoleAtOrganizationEnumApi
}

export type EnvironmentsDashboardsListParams = {
    format?: EnvironmentsDashboardsListFormat
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsDashboardsListFormat =
    (typeof EnvironmentsDashboardsListFormat)[keyof typeof EnvironmentsDashboardsListFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsListFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsDashboardsCreateParams = {
    format?: EnvironmentsDashboardsCreateFormat
}

export type EnvironmentsDashboardsCreateFormat =
    (typeof EnvironmentsDashboardsCreateFormat)[keyof typeof EnvironmentsDashboardsCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsCreateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsDashboardsRetrieveParams = {
    format?: EnvironmentsDashboardsRetrieveFormat
}

export type EnvironmentsDashboardsRetrieveFormat =
    (typeof EnvironmentsDashboardsRetrieveFormat)[keyof typeof EnvironmentsDashboardsRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsRetrieveFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsDashboardsUpdateParams = {
    format?: EnvironmentsDashboardsUpdateFormat
}

export type EnvironmentsDashboardsUpdateFormat =
    (typeof EnvironmentsDashboardsUpdateFormat)[keyof typeof EnvironmentsDashboardsUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsUpdateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsDashboardsPartialUpdateParams = {
    format?: EnvironmentsDashboardsPartialUpdateFormat
}

export type EnvironmentsDashboardsPartialUpdateFormat =
    (typeof EnvironmentsDashboardsPartialUpdateFormat)[keyof typeof EnvironmentsDashboardsPartialUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsPartialUpdateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsDashboardsDestroyParams = {
    format?: EnvironmentsDashboardsDestroyFormat
}

export type EnvironmentsDashboardsDestroyFormat =
    (typeof EnvironmentsDashboardsDestroyFormat)[keyof typeof EnvironmentsDashboardsDestroyFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsDestroyFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsDashboardsMoveTilePartialUpdateParams = {
    format?: EnvironmentsDashboardsMoveTilePartialUpdateFormat
}

export type EnvironmentsDashboardsMoveTilePartialUpdateFormat =
    (typeof EnvironmentsDashboardsMoveTilePartialUpdateFormat)[keyof typeof EnvironmentsDashboardsMoveTilePartialUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsMoveTilePartialUpdateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsDashboardsStreamTilesRetrieveParams = {
    format?: EnvironmentsDashboardsStreamTilesRetrieveFormat
}

export type EnvironmentsDashboardsStreamTilesRetrieveFormat =
    (typeof EnvironmentsDashboardsStreamTilesRetrieveFormat)[keyof typeof EnvironmentsDashboardsStreamTilesRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsStreamTilesRetrieveFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsDashboardsCreateFromTemplateJsonCreateParams = {
    format?: EnvironmentsDashboardsCreateFromTemplateJsonCreateFormat
}

export type EnvironmentsDashboardsCreateFromTemplateJsonCreateFormat =
    (typeof EnvironmentsDashboardsCreateFromTemplateJsonCreateFormat)[keyof typeof EnvironmentsDashboardsCreateFromTemplateJsonCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsCreateFromTemplateJsonCreateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsDashboardsCreateUnlistedDashboardCreateParams = {
    format?: EnvironmentsDashboardsCreateUnlistedDashboardCreateFormat
}

export type EnvironmentsDashboardsCreateUnlistedDashboardCreateFormat =
    (typeof EnvironmentsDashboardsCreateUnlistedDashboardCreateFormat)[keyof typeof EnvironmentsDashboardsCreateUnlistedDashboardCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const EnvironmentsDashboardsCreateUnlistedDashboardCreateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type EnvironmentsExportsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsFileSystemListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type EnvironmentsGroupsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Specify the group type to list
     */
    group_type_index: number
    /**
     * Search the group name
     */
    search: string
}

export type EnvironmentsGroupsActivityRetrieveParams = {
    /**
     * Specify the group type to find
     */
    group_type_index: number
    /**
     * Specify the id of the user to find groups for
     */
    id: string
}

export type EnvironmentsGroupsDeletePropertyCreateParams = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}

export type EnvironmentsGroupsFindRetrieveParams = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}

export type EnvironmentsGroupsRelatedRetrieveParams = {
    /**
     * Specify the group type to find
     */
    group_type_index: number
    /**
     * Specify the id of the user to find groups for
     */
    id: string
}

export type EnvironmentsGroupsUpdatePropertyCreateParams = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}

export type EnvironmentsIntegrationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsSubscriptionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DomainsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type InvitesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type MembersListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type List2Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type RolesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AnnotationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const CohortsPersonsRetrieveFormat = {
    csv: 'csv',
    json: 'json',
} as const

export type CommentsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
}

export type DashboardTemplatesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
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

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsListFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsCreateParams = {
    format?: DashboardsCreateFormat
}

export type DashboardsCreateFormat = (typeof DashboardsCreateFormat)[keyof typeof DashboardsCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsCreateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsRetrieveParams = {
    format?: DashboardsRetrieveFormat
}

export type DashboardsRetrieveFormat = (typeof DashboardsRetrieveFormat)[keyof typeof DashboardsRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsRetrieveFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsUpdateParams = {
    format?: DashboardsUpdateFormat
}

export type DashboardsUpdateFormat = (typeof DashboardsUpdateFormat)[keyof typeof DashboardsUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsUpdateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsPartialUpdateParams = {
    format?: DashboardsPartialUpdateFormat
}

export type DashboardsPartialUpdateFormat =
    (typeof DashboardsPartialUpdateFormat)[keyof typeof DashboardsPartialUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsPartialUpdateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsDestroyParams = {
    format?: DashboardsDestroyFormat
}

export type DashboardsDestroyFormat = (typeof DashboardsDestroyFormat)[keyof typeof DashboardsDestroyFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsDestroyFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsMoveTilePartialUpdateParams = {
    format?: DashboardsMoveTilePartialUpdateFormat
}

export type DashboardsMoveTilePartialUpdateFormat =
    (typeof DashboardsMoveTilePartialUpdateFormat)[keyof typeof DashboardsMoveTilePartialUpdateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsMoveTilePartialUpdateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsStreamTilesRetrieveParams = {
    format?: DashboardsStreamTilesRetrieveFormat
}

export type DashboardsStreamTilesRetrieveFormat =
    (typeof DashboardsStreamTilesRetrieveFormat)[keyof typeof DashboardsStreamTilesRetrieveFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsStreamTilesRetrieveFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsCreateFromTemplateJsonCreateParams = {
    format?: DashboardsCreateFromTemplateJsonCreateFormat
}

export type DashboardsCreateFromTemplateJsonCreateFormat =
    (typeof DashboardsCreateFromTemplateJsonCreateFormat)[keyof typeof DashboardsCreateFromTemplateJsonCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsCreateFromTemplateJsonCreateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type DashboardsCreateUnlistedDashboardCreateParams = {
    format?: DashboardsCreateUnlistedDashboardCreateFormat
}

export type DashboardsCreateUnlistedDashboardCreateFormat =
    (typeof DashboardsCreateUnlistedDashboardCreateFormat)[keyof typeof DashboardsCreateUnlistedDashboardCreateFormat]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const DashboardsCreateUnlistedDashboardCreateFormat = {
    json: 'json',
    txt: 'txt',
} as const

export type ExportsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type FileSystemListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type GroupsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Specify the group type to list
     */
    group_type_index: number
    /**
     * Search the group name
     */
    search: string
}

export type GroupsActivityRetrieveParams = {
    /**
     * Specify the group type to find
     */
    group_type_index: number
    /**
     * Specify the id of the user to find groups for
     */
    id: string
}

export type GroupsDeletePropertyCreateParams = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}

export type GroupsFindRetrieveParams = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}

export type GroupsRelatedRetrieveParams = {
    /**
     * Specify the group type to find
     */
    group_type_index: number
    /**
     * Specify the id of the user to find groups for
     */
    id: string
}

export type GroupsUpdatePropertyCreateParams = {
    /**
     * Specify the key of the group to find
     */
    group_key: string
    /**
     * Specify the group type to find
     */
    group_type_index: number
}

export type IntegrationsList2Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type PropertyDefinitionsListParams = {
    /**
     * If sent, response value will have `is_seen_on_filtered_events` populated. JSON-encoded
     * @minLength 1
     */
    event_names?: string
    /**
     * Whether to exclude core properties
     */
    exclude_core_properties?: boolean
    /**
     * Whether to exclude properties marked as hidden
     */
    exclude_hidden?: boolean
    /**
     * JSON-encoded list of excluded properties
     * @minLength 1
     */
    excluded_properties?: string
    /**
     * Whether to return only properties for events in `event_names`
     * @nullable
     */
    filter_by_event_names?: boolean | null
    /**
     * What group type is the property for. Only should be set if `type=group`
     */
    group_type_index?: number
    /**
     * Whether to return only (or excluding) feature flag properties
     * @nullable
     */
    is_feature_flag?: boolean | null
    /**
     * Whether to return only (or excluding) numerical property definitions
     * @nullable
     */
    is_numerical?: boolean | null
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Comma-separated list of properties to filter
     * @minLength 1
     */
    properties?: string
    /**
     * Searches properties by name
     */
    search?: string
    /**
 * What property definitions to return

* `event` - event
* `person` - person
* `group` - group
* `session` - session
 * @minLength 1
 */
    type?: PropertyDefinitionsListType
}

export type PropertyDefinitionsListType = (typeof PropertyDefinitionsListType)[keyof typeof PropertyDefinitionsListType]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PropertyDefinitionsListType = {
    event: 'event',
    person: 'person',
    group: 'group',
    session: 'session',
} as const

export type ScheduledChangesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type SubscriptionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UsersListParams = {
    email?: string
    is_staff?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
