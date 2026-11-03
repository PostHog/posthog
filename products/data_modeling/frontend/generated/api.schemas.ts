/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface EdgeSummaryApi {
    readonly id: string
    /** ID of the upstream node. */
    readonly source_id: string
    /** ID of the downstream node. */
    readonly target_id: string
}

export interface PaginatedEdgeSummaryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EdgeSummaryApi[]
}

export interface EdgeApi {
    readonly id: string
    /** ID of the upstream node. */
    readonly source_id: string
    /** ID of the downstream node. */
    readonly target_id: string
    properties?: unknown
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PatchedEdgeApi {
    readonly id?: string
    /** ID of the upstream node. */
    readonly source_id?: string
    /** ID of the downstream node. */
    readonly target_id?: string
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
 * * `metric` - Metric
 */
export type NodeTypeEnumApi = (typeof NodeTypeEnumApi)[keyof typeof NodeTypeEnumApi]

export const NodeTypeEnumApi = {
    Table: 'table',
    View: 'view',
    Matview: 'matview',
    Endpoint: 'endpoint',
    Metric: 'metric',
} as const

/**
 * * `sync_failed` - Sync Failed
 * * `unresolved` - Unresolved
 */
export type LineageIssueKindEnumApi = (typeof LineageIssueKindEnumApi)[keyof typeof LineageIssueKindEnumApi]

export const LineageIssueKindEnumApi = {
    SyncFailed: 'sync_failed',
    Unresolved: 'unresolved',
} as const

export interface LineageIssueApi {
    /** sync_failed when the last attempt to rebuild this node's edges ended in an error. unresolved when the rebuild finished but some of the names this node reads matched no node in the DAG.
     *
     * * `sync_failed` - Sync Failed
     * * `unresolved` - Unresolved */
    kind: LineageIssueKindEnumApi
    /** The error for sync_failed, or the comma-separated names that did not resolve for unresolved. */
    detail: string
    /**
     * When the issue was recorded.
     * @nullable
     */
    at: string | null
}

/**
 * * `posthog` - posthog
 * * `warehouse` - warehouse
 */
export type NodeOriginEnumApi = (typeof NodeOriginEnumApi)[keyof typeof NodeOriginEnumApi]

export const NodeOriginEnumApi = {
    Posthog: 'posthog',
    Warehouse: 'warehouse',
} as const

export interface NodeSuspensionApi {
    /** When the node was suspended. */
    at: string
    /** Error from the materialization that tripped suspension. */
    reason: string
    /** Materialization job that tripped suspension. */
    job_id: string
}

export interface NodeEndpointApi {
    /** Name of the endpoint this node's materialization backs. */
    name: string
    /** Endpoint version this node's materialization backs. */
    version: number
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
    /** @maxLength 1024 */
    description?: string
    /** @nullable */
    readonly saved_query_id: string | null
    /** @nullable */
    readonly metric_id: string | null
    readonly lineage_issue: LineageIssueApi | null
    /** Where a table originates, or null for legacy and unrecognized nodes.
     *
     * * `posthog` - posthog
     * * `warehouse` - warehouse */
    readonly origin: NodeOriginEnumApi | null
    /**
     * Warehouse table identifier for an imported table, or null when unavailable.
     * @nullable
     */
    readonly warehouse_table_id: string | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly upstream_count: number
    readonly downstream_count: number
    /** @nullable */
    readonly last_run_at: string | null
    /**
     * Skipped runs are written straight to the job table and never reach the stored status,
     * so a blocked model would keep reporting the success before it.
     * @nullable
     */
    readonly last_run_status: string | null
    /**
     * Error of the run that last_run_status describes, so the two never disagree.
     * @nullable
     */
    readonly last_run_error: string | null
    /** @nullable */
    readonly user_tag: string | null
    /** @nullable */
    readonly sync_interval: string | null
    /** Engines this node is suspended for after repeated materialization failures. Suspended engines are skipped by scheduled DAG runs until the node is resumed. */
    readonly suspended: NodeApiSuspended
    /** The endpoint version this node's materialization backs, or null for nodes that are not endpoints. */
    readonly endpoint: NodeEndpointApi | null
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
    /** @maxLength 1024 */
    description?: string
    /** @nullable */
    readonly saved_query_id?: string | null
    /** @nullable */
    readonly metric_id?: string | null
    readonly lineage_issue?: LineageIssueApi | null
    /** Where a table originates, or null for legacy and unrecognized nodes.
     *
     * * `posthog` - posthog
     * * `warehouse` - warehouse */
    readonly origin?: NodeOriginEnumApi | null
    /**
     * Warehouse table identifier for an imported table, or null when unavailable.
     * @nullable
     */
    readonly warehouse_table_id?: string | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    readonly upstream_count?: number
    readonly downstream_count?: number
    /** @nullable */
    readonly last_run_at?: string | null
    /**
     * Skipped runs are written straight to the job table and never reach the stored status,
     * so a blocked model would keep reporting the success before it.
     * @nullable
     */
    readonly last_run_status?: string | null
    /**
     * Error of the run that last_run_status describes, so the two never disagree.
     * @nullable
     */
    readonly last_run_error?: string | null
    /** @nullable */
    readonly user_tag?: string | null
    /** @nullable */
    readonly sync_interval?: string | null
    /** Engines this node is suspended for after repeated materialization failures. Suspended engines are skipped by scheduled DAG runs until the node is resumed. */
    readonly suspended?: PatchedNodeApiSuspended
    /** The endpoint version this node's materialization backs, or null for nodes that are not endpoints. */
    readonly endpoint?: NodeEndpointApi | null
}

export interface NodeResumeApi {
    /** False when the node was not suspended to begin with. */
    resumed: boolean
}

/**
 * * `upstream` - Upstream
 * * `downstream` - Downstream
 */
export type MaterializationRunDirectionEnumApi =
    (typeof MaterializationRunDirectionEnumApi)[keyof typeof MaterializationRunDirectionEnumApi]

export const MaterializationRunDirectionEnumApi = {
    Upstream: 'upstream',
    Downstream: 'downstream',
} as const

export interface NodeRunApi {
    /** Run this view with all upstream dependencies or all downstream dependents.
     *
     * * `upstream` - Upstream
     * * `downstream` - Downstream */
    direction: MaterializationRunDirectionEnumApi
}

export interface NodeRunResponseApi {
    /** The nodes included in the dependency run. */
    node_ids: string[]
}

export interface LineageResponseApi {
    /** Every node reachable from the requested one, plus the node itself. */
    nodes: NodeApi[]
    /** Every edge between two of those nodes. */
    edges: EdgeApi[]
}

export interface ModelUsageTotalsApi {
    /** Finished materialization runs, including failures and cancellations. */
    runs: number
    /** Runs with recorded usage. Other runs have unknown cost. */
    measured_runs: number
    /**
     * Measured bytes read, including probes and retries. Null if unmeasured.
     * @nullable
     */
    read_bytes: number | null
    /**
     * Measured rows read. Null if unmeasured.
     * @nullable
     */
    read_rows: number | null
    /**
     * Measured CPU microseconds. Null if unmeasured.
     * @nullable
     */
    cpu_microseconds: number | null
    /**
     * Measured ClickHouse query count. Null if unmeasured.
     * @nullable
     */
    query_count: number | null
}

export interface ModelUsageEngineApi {
    /** Finished materialization runs, including failures and cancellations. */
    runs: number
    /** Runs with recorded usage. Other runs have unknown cost. */
    measured_runs: number
    /**
     * Measured bytes read, including probes and retries. Null if unmeasured.
     * @nullable
     */
    read_bytes: number | null
    /**
     * Measured rows read. Null if unmeasured.
     * @nullable
     */
    read_rows: number | null
    /**
     * Measured CPU microseconds. Null if unmeasured.
     * @nullable
     */
    cpu_microseconds: number | null
    /**
     * Measured ClickHouse query count. Null if unmeasured.
     * @nullable
     */
    query_count: number | null
    /** Materialization engine: clickhouse or managed_warehouse. */
    engine: string
}

export interface ModelUsageDayApi {
    /** Finished materialization runs, including failures and cancellations. */
    runs: number
    /** Runs with recorded usage. Other runs have unknown cost. */
    measured_runs: number
    /**
     * Measured bytes read, including probes and retries. Null if unmeasured.
     * @nullable
     */
    read_bytes: number | null
    /**
     * Measured rows read. Null if unmeasured.
     * @nullable
     */
    read_rows: number | null
    /**
     * Measured CPU microseconds. Null if unmeasured.
     * @nullable
     */
    cpu_microseconds: number | null
    /**
     * Measured ClickHouse query count. Null if unmeasured.
     * @nullable
     */
    query_count: number | null
    /** UTC day on which the runs finished. */
    day: string
    /** Usage totals for each selected engine. */
    engines: ModelUsageEngineApi[]
}

export interface ModelUsageRowApi {
    /** Finished materialization runs, including failures and cancellations. */
    runs: number
    /** Runs with recorded usage. Other runs have unknown cost. */
    measured_runs: number
    /**
     * Measured bytes read, including probes and retries. Null if unmeasured.
     * @nullable
     */
    read_bytes: number | null
    /**
     * Measured rows read. Null if unmeasured.
     * @nullable
     */
    read_rows: number | null
    /**
     * Measured CPU microseconds. Null if unmeasured.
     * @nullable
     */
    cpu_microseconds: number | null
    /**
     * Measured ClickHouse query count. Null if unmeasured.
     * @nullable
     */
    query_count: number | null
    /**
     * Model ID, or null if permanently deleted.
     * @nullable
     */
    saved_query_id: string | null
    /** Model name. */
    name: string
    /** Whether this model has been deleted. */
    deleted: boolean
    /** Usage totals for each selected engine. */
    engines: ModelUsageEngineApi[]
}

export interface ModelStatusModelApi {
    /** Model ID. */
    saved_query_id: string
    /** Model name. */
    name: string
    /** Whether this model has been deleted. */
    deleted: boolean
}

export interface ModelStatusBreakdownApi {
    /** Materialization engine: clickhouse or managed_warehouse. */
    engine: string
    /** Status of the latest run for the model and engine in this range. */
    status: string
    /** Number of models whose latest run has this status. */
    count: number
    /** Models whose latest run has this status. */
    models: ModelStatusModelApi[]
}

export interface ModelUsageApi {
    /** Inclusive UTC start date. */
    date_from: string
    /** Exclusive UTC end date. Today's incomplete usage is excluded. */
    date_to: string
    /** Totals over the whole date range. */
    overview: ModelUsageTotalsApi
    /** Daily usage, attributed to when each run finished. */
    trends: ModelUsageDayApi[]
    /** Model breakdown in the requested sort order. */
    models: ModelUsageRowApi[]
    /** Total number of models in the breakdown. */
    count: number
    /** Latest run status for each model and engine in the selected complete-day range. */
    status_breakdown: ModelStatusBreakdownApi[]
    /**
     * Latest usage collection timestamp in this range.
     * @nullable
     */
    usage_updated_at: string | null
}

export type DataModelingEdgesListParams = {
    /**
     * A page number within the paginated result set.
     */
    page?: number
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

export type DataModelingNodesRetrieveParams = {
    /**
     * Resolve the path ID as this backing resource type instead of a node ID.
     */
    lookup?: DataModelingNodesRetrieveLookup
}

export type DataModelingNodesRetrieveLookup =
    (typeof DataModelingNodesRetrieveLookup)[keyof typeof DataModelingNodesRetrieveLookup]

export const DataModelingNodesRetrieveLookup = {
    Metric: 'metric',
    PosthogTable: 'posthog_table',
    SavedQuery: 'saved_query',
    WarehouseTable: 'warehouse_table',
} as const

export type DataModelingNodesLineageRetrieveParams = {
    /**
     * Data catalog metric to build lineage for, resolved to its node. Alternative to node_id.
     */
    metric_id?: string
    /**
     * Node to build lineage for.
     */
    node_id?: string
    /**
     * Saved query to build lineage for, resolved to its node. Alternative to node_id.
     */
    saved_query_id?: string
}

export type DataModelingUsageListParams = {
    /**
     * Inclusive UTC start date for a custom range, up to 366 complete days.
     */
    date_from?: string
    /**
     * Inclusive UTC end date for a custom range. Today is always excluded.
     */
    date_to?: string
    /**
     * Number of complete UTC days, up to 90.
     * @minimum 1
     * @maximum 90
     */
    days?: number
    /**
     * Materialization engine. All combines ClickHouse and managed warehouse usage.
     *
     * * `all` - All
     * * `clickhouse` - ClickHouse
     * * `managed_warehouse` - Managed warehouse
     * @minLength 1
     */
    engine?: DataModelingUsageListEngine
    /**
     * Model breakdown page, starting at 1.
     * @minimum 1
     */
    page?: number
    /**
     * Models per page, up to 100.
     * @minimum 1
     * @maximum 100
     */
    page_size?: number
    /**
     * Limit usage to one accessible materialized view.
     */
    saved_query_id?: string
    /**
     * Comma-separated materialized view IDs. Usage is limited to accessible views.
     * @minLength 1
     */
    saved_query_ids?: string
    /**
     * Column to sort models by.
     *
     * * `name` - Model
     * * `read_bytes` - Bytes read
     * * `clickhouse_read_bytes` - ClickHouse bytes
     * * `managed_warehouse_read_bytes` - Managed warehouse bytes
     * * `cpu_microseconds` - CPU time
     * * `runs` - Runs
     * @minLength 1
     */
    sort_by?: DataModelingUsageListSortBy
    /**
     * Sort direction. Unmeasured values are always last.
     *
     * * `asc` - Ascending
     * * `desc` - Descending
     * @minLength 1
     */
    sort_direction?: DataModelingUsageListSortDirection
}

export type DataModelingUsageListEngine = (typeof DataModelingUsageListEngine)[keyof typeof DataModelingUsageListEngine]

export const DataModelingUsageListEngine = {
    All: 'all',
    Clickhouse: 'clickhouse',
    ManagedWarehouse: 'managed_warehouse',
} as const

export type DataModelingUsageListSortBy = (typeof DataModelingUsageListSortBy)[keyof typeof DataModelingUsageListSortBy]

export const DataModelingUsageListSortBy = {
    Name: 'name',
    ReadBytes: 'read_bytes',
    ClickhouseReadBytes: 'clickhouse_read_bytes',
    ManagedWarehouseReadBytes: 'managed_warehouse_read_bytes',
    CpuMicroseconds: 'cpu_microseconds',
    Runs: 'runs',
} as const

export type DataModelingUsageListSortDirection =
    (typeof DataModelingUsageListSortDirection)[keyof typeof DataModelingUsageListSortDirection]

export const DataModelingUsageListSortDirection = {
    Asc: 'asc',
    Desc: 'desc',
} as const
