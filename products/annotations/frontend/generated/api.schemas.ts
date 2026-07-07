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
 * * `USR` - user
 * * `GIT` - GitHub
 */
export type CreationTypeEnumApi = (typeof CreationTypeEnumApi)[keyof typeof CreationTypeEnumApi]

export const CreationTypeEnumApi = {
    Usr: 'USR',
    Git: 'GIT',
} as const

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
 * * `dashboard_item` - insight
 * * `dashboard` - dashboard
 * * `project` - project
 * * `organization` - organization
 * * `tag` - tag
 * * `recording` - recording
 */
export type AnnotationScopeEnumApi = (typeof AnnotationScopeEnumApi)[keyof typeof AnnotationScopeEnumApi]

export const AnnotationScopeEnumApi = {
    DashboardItem: 'dashboard_item',
    Dashboard: 'dashboard',
    Project: 'project',
    Organization: 'organization',
    Tag: 'tag',
    Recording: 'recording',
} as const

/**
 * Serializer mixin that handles tags for objects.
 */
export interface AnnotationApi {
    readonly id: number
    /**
     * Annotation text shown on charts to describe the change, release, or incident.
     * @maxLength 8192
     * @nullable
     */
    content?: string | null
    /**
     * When this annotation happened (ISO 8601 timestamp). Used to position it on charts.
     * @nullable
     */
    date_marker?: string | null
    /** Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.
     *
     * * `USR` - user
     * * `GIT` - GitHub */
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
    /** Soft-delete flag. Set to true to hide the annotation, or false to restore it. */
    deleted?: boolean
    /** Annotation visibility scope: `project`, `organization`, `dashboard`, `dashboard_item`, or `tag`. With `tag`, the annotation shows on every dashboard and insight carrying one of the annotation's `tags`. `recording` is deprecated and rejected.
     *
     * * `dashboard_item` - insight
     * * `dashboard` - dashboard
     * * `project` - project
     * * `organization` - organization
     * * `tag` - tag
     * * `recording` - recording */
    scope?: AnnotationScopeEnumApi
    /**
     * Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.
     * @maxLength 16
     * @nullable
     */
    emoji?: string | null
    /**
     * When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.
     * @nullable
     */
    hidden_in_user_interface?: boolean | null
    /** Tag names this annotation is scoped to. When `scope` is `tag`, the annotation is shown on every dashboard and insight carrying one of these tags. Required (non-empty) when `scope` is `tag`. */
    tags?: string[]
}

export interface PaginatedAnnotationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AnnotationApi[]
}

/**
 * Serializer mixin that handles tags for objects.
 */
export interface PatchedAnnotationApi {
    readonly id?: number
    /**
     * Annotation text shown on charts to describe the change, release, or incident.
     * @maxLength 8192
     * @nullable
     */
    content?: string | null
    /**
     * When this annotation happened (ISO 8601 timestamp). Used to position it on charts.
     * @nullable
     */
    date_marker?: string | null
    /** Who created this annotation. Use `USR` for user-created notes and `GIT` for bot/deployment notes.
     *
     * * `USR` - user
     * * `GIT` - GitHub */
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
    /** Soft-delete flag. Set to true to hide the annotation, or false to restore it. */
    deleted?: boolean
    /** Annotation visibility scope: `project`, `organization`, `dashboard`, `dashboard_item`, or `tag`. With `tag`, the annotation shows on every dashboard and insight carrying one of the annotation's `tags`. `recording` is deprecated and rejected.
     *
     * * `dashboard_item` - insight
     * * `dashboard` - dashboard
     * * `project` - project
     * * `organization` - organization
     * * `tag` - tag
     * * `recording` - recording */
    scope?: AnnotationScopeEnumApi
    /**
     * Optional emoji shown in place of the default badge when this annotation is surfaced on a chart.
     * @maxLength 16
     * @nullable
     */
    emoji?: string | null
    /**
     * When true, the annotation is hidden from the PostHog UI (charts and the annotations list) but still readable over the API and MCP. Use for high-frequency markers like deployments that would otherwise crowd the UI. Null (the default) means the annotation is shown.
     * @nullable
     */
    hidden_in_user_interface?: boolean | null
    /** Tag names this annotation is scoped to. When `scope` is `tag`, the annotation is shown on every dashboard and insight carrying one of these tags. Required (non-empty) when `scope` is `tag`. */
    tags?: string[]
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
