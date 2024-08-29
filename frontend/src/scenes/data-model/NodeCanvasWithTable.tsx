import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import GenericNode from './Node'
import { FixedField, JoinedField, TableFields } from './TableFields'
import { Edge, Node, NodePosition, NodePositionWithBounds, NodeWithDepth, Position } from './types'

const assignDepths = (nodes: Node[]): NodeWithDepth[] => {
    const nodeMap: { [id: string]: NodeWithDepth } = {}

    // Initialize all nodes with depth -1
    nodes.forEach((node) => {
        nodeMap[node.nodeId] = { ...node, depth: -1 }
    })

    const assignDepthRecursive = (nodeId: string, currentDepth: number): void => {
        const node = nodeMap[nodeId]
        if (!node || node.depth !== -1) {
            return
        } // Skip if node doesn't exist or already processed

        node.depth = currentDepth

        // Process leaf nodes
        node.leaf.forEach((leafId) => {
            if (nodeMap[leafId]) {
                assignDepthRecursive(leafId, currentDepth + 1)
            }
        })
    }

    // Start assigning depths from each unprocessed node
    nodes.forEach((node) => {
        if (nodeMap[node.nodeId].depth === -1) {
            assignDepthRecursive(node.nodeId, 0)
        }
    })

    return Object.values(nodeMap)
}

const calculateNodePositions = (nodesWithDepth: NodeWithDepth[]): NodePosition[] => {
    const padding = 50
    const verticalSpacing = 150
    const horizontalSpacing = 300
    // Order nodes by depth
    nodesWithDepth.sort((a, b) => a.depth - b.depth)

    // Create a map to store the next available row for each depth
    const depthRowMap: { [key: number]: number } = {}

    // Update node positions based on depth
    const nodePositions = nodesWithDepth.map((node) => {
        const col = node.depth

        // If this is the first node at this depth, initialize the row
        if (depthRowMap[col] === undefined) {
            depthRowMap[col] = 0
        }

        // Reset row to match root if new column
        if (col > 0 && depthRowMap[col] === 0) {
            depthRowMap[col] = depthRowMap[0] - 1 || 0
        }

        const row = depthRowMap[col]

        // Update the next available row for this depth
        depthRowMap[col] = row + 1

        return {
            ...node,
            position: {
                x: padding + col * horizontalSpacing,
                y: padding + row * verticalSpacing,
            },
        }
    })

    return nodePositions
}

const calculateTablePosition = (nodePositions: NodePosition[]): Position => {
    // Find the node with the maximum x position
    const farthestNode = nodePositions.reduce((max, node) => (node.position.x > max.position.x ? node : max))

    // Calculate the table position to be slightly to the right of the farthest node
    const tablePosition: Position = {
        x: farthestNode.position.x + 300, // Add some padding
        y: 100, // Fixed y position for the table
    }

    return tablePosition
}

const calculateEdges = (nodeRefs: (HTMLDivElement | null)[], nodes: NodePosition[]): Edge[] => {
    const nodes_map = nodes.reduce((acc: Record<string, NodePosition>, node) => {
        acc[node.nodeId] = node
        return acc
    }, {})

    const dfs = (nodeId: string, visited: Set<string> = new Set(), depth: number = 0): Edge[] => {
        if (visited.has(nodeId)) {
            return []
        }
        visited.add(nodeId)

        const node = nodes_map[nodeId]
        if (!node) {
            return []
        }

        const nodeRef = nodeRefs.find((ref) => ref?.id === nodeId)
        if (!nodeRef) {
            return []
        }

        const edges: Edge[] = []
        const fromWithBounds = calculateBound(node, nodeRef)

        for (let i = 0; i < node.leaf.length; i++) {
            const leafId = node.leaf[i]
            const toNode = nodes_map[leafId]
            const toRef = nodeRefs.find((ref) => ref?.id === leafId)

            if (toNode && toRef) {
                const toWithBounds = calculateBound(toNode, toRef)
                const newEdges = calculateEdgesFromTo(fromWithBounds, toWithBounds)
                edges.push(...newEdges)
            }

            depth = i > 0 ? depth + 1 : depth
            edges.push(...dfs(leafId, visited, depth))
        }

        return edges
    }

    const edges: Edge[] = []

    const visited = new Set<string>()
    for (const node of nodes) {
        if (!visited.has(node.nodeId)) {
            edges.push(...dfs(node.nodeId, visited))
        }
    }

    return edges
}

const calculateBound = (node: NodePosition, ref: HTMLDivElement | null): NodePositionWithBounds => {
    if (!ref) {
        return {
            ...node,
            left: null,
            right: null,
        }
    }

    const { x, y } = node.position
    const { width, height } = ref.getBoundingClientRect()
    return {
        ...node,
        left: { x, y: y + height / 2 },
        right: { x: x + width, y: y + height / 2 },
    }
}

const calculateEdgesFromTo = (from: NodePositionWithBounds, to: NodePositionWithBounds): Edge[] => {
    if (!from.right || !to.left) {
        return []
    }

    const edges = []
    edges.push({
        from: from.right,
        to: to.left,
    })

    return edges
}

interface ScrollableDraggableCanvasProps {
    nodes: Node[]
    fixedFields: FixedField[]
    joinedFields: JoinedField[]
    tableName: string
}

const NodeCanvasWithTable = ({
    nodes,
    fixedFields,
    joinedFields,
    tableName,
}: ScrollableDraggableCanvasProps): JSX.Element => {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [isDragging, setIsDragging] = useState(false)
    const [offset, setOffset] = useState({ x: 0, y: 0 })
    const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
    const rowsRefs = useRef<(HTMLDivElement | null)[]>(Array(joinedFields.length).fill(null))
    const nodeRefs = useRef<(HTMLDivElement | null)[]>(Array(nodes.length).fill(null))
    const tableNodeRef = useRef<HTMLDivElement | null>(null)
    const [nodePositions, setNodePositions] = useState<NodePosition[]>([])
    const [tablePosition, setTablePosition] = useState<Position>({ x: 0, y: 0 })
    const [edges, setEdges] = useState<Edge[]>([])

    useEffect(() => {
        const nodesWithDepth = assignDepths(nodes)
        const nodePositions = calculateNodePositions(nodesWithDepth)
        setNodePositions(nodePositions)
        const tablePosition = calculateTablePosition(nodePositions)
        setTablePosition(tablePosition)
    }, [])

    useEffect(() => {
        const allNodes = [...nodePositions]
        // calculated table row positions
        rowsRefs.current.forEach((ref) => {
            const rect = ref?.getBoundingClientRect()
            const nodeRect = tableNodeRef.current?.getBoundingClientRect()

            if (!rect) {
                return
            }

            if (nodeRect && ref) {
                allNodes.push({
                    nodeId: ref.id,
                    name: 'Table',
                    position: { x: tablePosition.x, y: tablePosition.y + (rect.y - nodeRect.y) },
                    leaf: [],
                    depth: -1,
                })
            }
        })

        const calculatedEdges = calculateEdges([...nodeRefs.current, ...rowsRefs.current], allNodes)
        setEdges(calculatedEdges)
    }, [nodePositions, tablePosition])

    const drawGrid = (ctx: CanvasRenderingContext2D, canvasWidth: number, canvasHeight: number): void => {
        ctx.fillStyle = '#000000'
        ctx.imageSmoothingEnabled = true
        const dotSize = 0.5
        const spacing = 10

        for (let x = offset.x % spacing; x < canvasWidth; x += spacing) {
            for (let y = offset.y % spacing; y < canvasHeight; y += spacing) {
                ctx.fillRect(x, y, dotSize, dotSize)
            }
        }
    }

    useEffect(() => {
        const canvas = canvasRef.current

        if (canvas) {
            const ctx = canvas.getContext('2d')
            if (!ctx) {
                return
            }
            const { width, height } = canvas.getBoundingClientRect()

            canvas.width = width
            canvas.height = height

            drawGrid(ctx, width, height)
        }

        const handleResize = (): void => {
            if (canvas) {
                const { width, height } = canvas.getBoundingClientRect()
                canvas.width = width
                canvas.height = height
                const ctx = canvas.getContext('2d')
                if (ctx) {
                    drawGrid(ctx, width, height)
                }
            }
        }

        window.addEventListener('resize', handleResize)

        return () => {
            window.removeEventListener('resize', handleResize)
        }
    }, [offset, nodePositions])

    const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>): void => {
        setIsDragging(true)
        setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y })
    }

    const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>): void => {
        if (!isDragging) {
            return
        }
        const newOffset = {
            x: e.clientX - dragStart.x,
            y: e.clientY - dragStart.y,
        }
        setOffset(newOffset)
    }

    const handleMouseUp = (): void => {
        setIsDragging(false)
    }

    return (
        <div className="relative w-full h-[95vh]">
            <canvas
                ref={canvasRef}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
                className={clsx('w-full h-full', isDragging ? 'cursor-grabbing' : 'cursor-grab')}
            />
            <svg className="absolute top-0 left-0 w-full h-full pointer-events-none">
                {edges.map((edge, index) => {
                    const controlPoint1X = edge.from.x + offset.x + (edge.to.x - edge.from.x) / 3
                    const controlPoint1Y = edge.from.y + offset.y
                    const controlPoint2X = edge.to.x + offset.x - (edge.to.x - edge.from.x) / 3
                    const controlPoint2Y = edge.to.y + offset.y
                    return (
                        <path
                            key={index}
                            d={`M ${edge.from.x + offset.x} ${edge.from.y + offset.y} 
                               C ${controlPoint1X} ${controlPoint1Y}, 
                                 ${controlPoint2X} ${controlPoint2Y}, 
                                 ${edge.to.x + offset.x} ${edge.to.y + offset.y}`}
                            stroke="black"
                            strokeWidth="2"
                            fill="none"
                        />
                    )
                })}
            </svg>
            {nodePositions.map(({ name, position, nodeId }, idx) => {
                return (
                    <div
                        key={nodeId}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            position: 'absolute',
                            left: `${position.x + offset.x}px`,
                            top: `${position.y + offset.y}px`,
                        }}
                    >
                        <GenericNode
                            pref={(el: HTMLDivElement | null) => {
                                nodeRefs.current[idx] = el
                                nodeRefs.current[idx]?.setAttribute('id', nodeId)
                            }}
                        >
                            {name}
                        </GenericNode>
                    </div>
                )
            })}

            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'absolute',
                    left: `${tablePosition.x + offset.x}px`,
                    top: `${tablePosition.y + offset.y}px`,
                }}
            >
                <TableFieldNode
                    fixedFields={fixedFields}
                    joinedFields={joinedFields}
                    nodeRef={tableNodeRef}
                    rowsRefs={rowsRefs}
                    tableName={tableName}
                />
            </div>
        </div>
    )
}

export default NodeCanvasWithTable

interface TableFieldNodeProps {
    fixedFields: FixedField[]
    joinedFields: JoinedField[]
    rowsRefs: React.MutableRefObject<(HTMLDivElement | null)[]>
    nodeRef: React.MutableRefObject<HTMLDivElement | null>
    tableName: string
}

function TableFieldNode({ nodeRef, rowsRefs, fixedFields, joinedFields, tableName }: TableFieldNodeProps): JSX.Element {
    return (
        <div ref={nodeRef} className="w-[500px] bg-white border border-black border-2 rounded-lg">
            <TableFields
                fixedFields={fixedFields}
                joinedFields={joinedFields}
                rowsRefs={rowsRefs}
                tableName={tableName}
            />
        </div>
    )
}
