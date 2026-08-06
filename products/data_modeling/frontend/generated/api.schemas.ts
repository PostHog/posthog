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
    /** True when this team's DAG schedules are driven by per-model freshness targets, so `sync_frequency` no longer controls scheduling and writes to it are rejected. False when the DAG-level frequency still applies. */
    readonly frequency_managed_by_nodes: boolean
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

export interface PatchedDAGApi {
    readonly id?: string
    /**
     * Human-readable name for this DAG
     * @maxLength 2048
     */
    name?: string
    /** Optional description of the DAG's purpose */
    description?: string
    /**
     * Sync frequency string (e.g. '24hour', '7day')
     * @nullable
     */
    sync_frequency?: string | null
    /** True when this team's DAG schedules are driven by per-model freshness targets, so `sync_frequency` no longer controls scheduling and writes to it are rejected. False when the DAG-level frequency still applies. */
    readonly frequency_managed_by_nodes?: boolean
    readonly node_count?: number
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
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

export interface PatchedEdgeApi {
    readonly id?: string
    readonly source_id?: string
    readonly target_id?: string
    dag?: string
    readonly dag_name?: string
    properties?: unknown
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
}

/**
 * * `table` - Table
 * * `view` - View
 * * `matview` - Mat View
 * * `endpoint` - Endpoint
 */
export type NodeTypeEnumApi = (typeof NodeTypeEnumApi)[keyof typeof NodeTypeEnumApi]

export const NodeTypeEnumApi = {
    Table: 'table',
    View: 'view',
    Matview: 'matview',
    Endpoint: 'endpoint',
} as const

export interface NodeSuspensionApi {
    /** When the node was suspended. */
    at: string
    /** Error from the materialization that tripped suspension. */
    reason: string
    /** Materialization job that tripped suspension. */
    job_id: string
}

/**
 * Engines this node is suspended for after repeated materialization failures. Suspended engines are skipped by scheduled DAG runs until the node is resumed.
 */
export type NodeApiSuspended = { [key: string]: NodeSuspensionApi }

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
    /** Engines this node is suspended for after repeated materialization failures. Suspended engines are skipped by scheduled DAG runs until the node is resumed. */
    readonly suspended: NodeApiSuspended
}

export interface PaginatedNodeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: NodeApi[]
}

/**
 * Engines this node is suspended for after repeated materialization failures. Suspended engines are skipped by scheduled DAG runs until the node is resumed.
 */
export type PatchedNodeApiSuspended = { [key: string]: NodeSuspensionApi }

export interface PatchedNodeApi {
    readonly id?: string
    /** @maxLength 2048 */
    name?: string
    type?: NodeTypeEnumApi
    dag?: string
    readonly dag_name?: string
    /** @maxLength 1024 */
    description?: string
    /** @nullable */
    readonly saved_query_id?: string | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    readonly upstream_count?: number
    readonly downstream_count?: number
    /** @nullable */
    readonly last_run_at?: string | null
    /** @nullable */
    readonly last_run_status?: string | null
    /** @nullable */
    readonly user_tag?: string | null
    /** @nullable */
    readonly sync_interval?: string | null
    /** Engines this node is suspended for after repeated materialization failures. Suspended engines are skipped by scheduled DAG runs until the node is resumed. */
    readonly suspended?: PatchedNodeApiSuspended
}

export interface NodeResumeApi {
    /** False when the node was not suspended to begin with. */
    resumed: boolean
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

export type DataModelingNodesLineageRetrieveParams = {
    /**
     * Node to build lineage for.
     */
    node_id?: string
    /**
     * Saved query to build lineage for, resolved to its node. Alternative to node_id.
     */
    saved_query_id?: string
}
