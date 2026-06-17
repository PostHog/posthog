// Types mirror the `lineage` / `graph` action responses from
// products/data_modeling/backend/api/node.py (NodeSerializer + EdgeSerializer).
// Kept standalone (not imported from generated Orval types) so the UI app bundle
// is self-contained.

export type DataModelNodeType = 'table' | 'view' | 'matview' | 'endpoint'

export interface DataModelNode {
    id: string
    name: string
    type: DataModelNodeType
    dag?: string
    dag_name?: string
    description?: string | null
    saved_query_id?: string | null
    upstream_count: number
    downstream_count: number
    last_run_at?: string | null
    last_run_status?: string | null
    user_tag?: string | null
    sync_interval?: string | null
}

export interface DataModelEdge {
    id: string
    source_id: string
    target_id: string
    dag?: string
    dag_name?: string
}

export interface DataModelGraphData {
    nodes: DataModelNode[]
    edges: DataModelEdge[]
    /** Node the lineage is centered on; null for the whole-DAG graph view. */
    focal_id: string | null
    _posthogUrl?: string
}

/** Role of a node relative to the currently focused node. */
export type NodeRole = 'focal' | 'upstream' | 'downstream' | 'other'
