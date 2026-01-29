/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface EdgeApi {
    readonly id: string
    readonly source_id: string
    readonly target_id: string
    readonly dag_id: string
    properties?: unknown
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedEdgeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EdgeApi[]
}

/**
 * * `table` - Table
 * `view` - View
 * `matview` - Mat View
 */
export type NodeTypeEnumApi = (typeof NodeTypeEnumApi)[keyof typeof NodeTypeEnumApi]

export const NodeTypeEnumApi = {
    table: 'table',
    view: 'view',
    matview: 'matview',
} as const

export interface NodeApi {
    readonly id: string
    /** @maxLength 2048 */
    name: string
    type?: NodeTypeEnumApi
    /** @maxLength 256 */
    dag_id?: string
    /** @nullable */
    readonly saved_query_id: string | null
    properties?: unknown
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly upstream_count: number
    readonly downstream_count: number
    /** @nullable */
    readonly last_run_at: string | null
}

export interface PaginatedNodeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: NodeApi[]
}

export type DataModelingEdgesListParams = {
    /**
     * A page number within the paginated result set.
     */
    page?: number
    /**
     * A search term.
     */
    search?: string
}

export type DataModelingNodesListParams = {
    /**
     * A page number within the paginated result set.
     */
    page?: number
    /**
     * A search term.
     */
    search?: string
}
