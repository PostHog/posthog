import { Node, Position } from '@xyflow/react'

import { DataModelingJobStatus, DataModelingNodeType } from '~/types'

export interface ModelNodeHandle {
    id?: string
    type: 'source' | 'target'
    position: Position
    x?: number
    y?: number
}

export interface ModelNodeData extends Record<string, unknown> {
    id: string
    name: string
    type: DataModelingNodeType
    dagId?: string
    savedQueryId?: string
    handles?: ModelNodeHandle[]
    userTag?: string
    upstreamCount: number
    downstreamCount: number
    // derived state for reactflow optimization
    isSelected?: boolean
    isRunning?: boolean
    isTypeHighlighted?: boolean
    isSearchMatch?: boolean
    lastJobStatus?: DataModelingJobStatus
}

export type ModelNode = Node<ModelNodeData>

export interface ModelEdge {
    from: string
    to: string
    type: 'dependency'
}

export interface DataModelingGraph {
    nodes: ModelNodeData[]
    edges: ModelEdge[]
}

export interface CreateModelNodeType {
    type: DataModelingNodeType
    name: string
    description?: string
}

export interface ModelNodeProps {
    id: string
    data: ModelNodeData
    selected?: boolean
}
