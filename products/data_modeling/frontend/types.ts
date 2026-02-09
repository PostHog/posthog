import { Position, Edge as ReactFlowEdge, Node as ReactFlowNode } from '@xyflow/react'

import { DataModelingJobStatus, DataModelingNodeType, DataWarehouseSyncInterval } from '~/types'

export interface NodeHandle {
    id?: string
    type: 'source' | 'target'
    position: Position
    x?: number
    y?: number
}

export interface NodeData extends Record<string, unknown> {
    id: string
    name: string
    type: DataModelingNodeType
    dagId?: string
    savedQueryId?: string
    handles?: NodeHandle[]
    upstreamCount: number
    downstreamCount: number
    // derived state for reactflow optimization
    isRunning?: boolean
    isTypeHighlighted?: boolean
    isSearchMatch?: boolean
    userTag?: string
    lastRunAt?: string
    lastJobStatus?: DataModelingJobStatus
    syncInterval?: DataWarehouseSyncInterval
}

export interface EdgeData extends Record<string, unknown> {
    from: string
    to: string
    type: 'dependency'
}

export type ViewMode = 'list' | 'graph'

export type SearchMode = 'search' | 'tag' | 'upstream' | 'downstream' | 'all'

export type ElkDirection = 'DOWN' | 'RIGHT'

export type Node = ReactFlowNode<NodeData>
export type Edge = ReactFlowEdge<EdgeData>

export interface Graph {
    nodes: Node[]
    edges: Edge[]
}

export interface CreateModelNodeType {
    type: DataModelingNodeType
    name: string
    description?: string
}
