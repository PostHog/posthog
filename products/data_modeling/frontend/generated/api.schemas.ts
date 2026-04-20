/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface DagApi {
    readonly id: string
    /**
     * Human-readable name for this DAG
     * @maxLength 2048
     */
    name: string
    /** Optional description of the DAG's purpose */
    description?: string
    /**
     * Sync frequency string (e.g. '24hour', '7day')
     * @nullable
     */
    sync_frequency?: string | null
    readonly node_count: number
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedDAGListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DagApi[]
}

export interface EdgeApi {
    readonly id: string
    readonly source_id: string
    readonly target_id: string
    dag: string
    readonly dag_name: string
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
 * `endpoint` - Endpoint
 */
export type NodeTypeEnumApi = (typeof NodeTypeEnumApi)[keyof typeof NodeTypeEnumApi]

export const NodeTypeEnumApi = {
    Table: 'table',
    View: 'view',
    Matview: 'matview',
    Endpoint: 'endpoint',
} as const

export interface NodeApi {
    readonly id: string
    /** @maxLength 2048 */
    name: string
    type?: NodeTypeEnumApi
    dag: string
    readonly dag_name: string
    /** @maxLength 1024 */
    description?: string
    /** @nullable */
    readonly saved_query_id: string | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly upstream_count: number
    readonly downstream_count: number
    /** @nullable */
    readonly last_run_at: string | null
    /** @nullable */
    readonly last_run_status: string | null
    /** @nullable */
    readonly user_tag: string | null
    /** @nullable */
    readonly sync_interval: string | null
}

export interface PaginatedNodeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: NodeApi[]
}

export type DataModelingDagsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
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
