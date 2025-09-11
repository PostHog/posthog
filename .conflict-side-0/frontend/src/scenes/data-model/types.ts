export interface Position {
    x: number
    y: number
}

export interface Node {
    nodeId: string
    name: string
    savedQueryId?: string
    leaf: string[]
}

export interface NodeWithDepth extends Node {
    depth: number
}

export interface NodePosition extends NodeWithDepth {
    position: Position
}

export interface Edge {
    from: Position
    to: Position
}

export interface NodePositionWithBounds extends NodePosition {
    left: Position | null
    right: Position | null
}
