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

export interface GatewayApi {
    readonly id: string
    /**
     * Lowercase, URL-safe identifier (letters, digits, '-' or '_', no leading/trailing separator). This is the $ai_gateway_slug billing-attribution value the LLM gateway records for every request a bound credential makes.
     * @maxLength 64
     */
    slug: string
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly created_by: UserBasicApi | null
    /** Number of project secret keys and OAuth applications that attribute usage to this gateway. */
    readonly bound_credentials_count: number
}

export interface PaginatedGatewayListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: GatewayApi[]
}

export interface PatchedGatewayApi {
    readonly id?: string
    /**
     * Lowercase, URL-safe identifier (letters, digits, '-' or '_', no leading/trailing separator). This is the $ai_gateway_slug billing-attribution value the LLM gateway records for every request a bound credential makes.
     * @maxLength 64
     */
    slug?: string
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    readonly created_by?: UserBasicApi | null
    /** Number of project secret keys and OAuth applications that attribute usage to this gateway. */
    readonly bound_credentials_count?: number
}

export interface AssignCredentialApi {
    /** Id of one of the team's unassigned project secret keys to assign to this gateway. */
    credential_id: string
}

export interface BoundProjectSecretAPIKeyApi {
    /** Project secret API key id. */
    readonly id: string
    /** The key's human-readable label. */
    readonly label: string
    /**
     * When the key was last used, if ever.
     * @nullable
     */
    readonly last_used_at: string | null
}

export interface BoundOAuthApplicationApi {
    /** OAuth application id. */
    readonly id: string
    /** The application's name. */
    readonly name: string
    /** The application's OAuth client id. */
    readonly client_id: string
}

export interface GatewayBoundCredentialsApi {
    /** Project secret keys bound to this gateway. */
    readonly project_secret_api_keys: readonly BoundProjectSecretAPIKeyApi[]
    /** OAuth applications bound to this gateway. */
    readonly oauth_applications: readonly BoundOAuthApplicationApi[]
}

/**
 * * `project_secret_api_key` - project_secret_api_key
 * `oauth_application` - oauth_application
 */
export type CredentialTypeEnumApi = (typeof CredentialTypeEnumApi)[keyof typeof CredentialTypeEnumApi]

export const CredentialTypeEnumApi = {
    ProjectSecretApiKey: 'project_secret_api_key',
    OauthApplication: 'oauth_application',
} as const

export interface UnassignCredentialApi {
    /** Which kind of credential to unassign.

  * `project_secret_api_key` - project_secret_api_key
  * `oauth_application` - oauth_application */
    credential_type: CredentialTypeEnumApi
    /** Id of the credential to unassign from this gateway. */
    credential_id: string
}

export interface AssignableCredentialApi {
    /** Project secret API key id. */
    readonly id: string
    /** The key's human-readable label. */
    readonly label: string
    /**
     * When the key was last used, if ever.
     * @nullable
     */
    readonly last_used_at: string | null
}

export type GatewaysListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
