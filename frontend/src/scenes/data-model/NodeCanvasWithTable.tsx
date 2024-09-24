import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { StatusTagSetting } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'

import GenericNode from './Node'
import { FixedField, JoinedField, TableFields } from './TableFields'
import { Edge, Node, NodePosition, NodePositionWithBounds, NodeWithDepth, Position } from './types'

const VERTICAL_SPACING = 150
const HORIZONTAL_SPACING = 250

// TODO: Refactor this to be done in the backend
const assignDepths = (nodes: Node[]): NodeWithDepth[] => {
    const nodeMap: { [id: string]: NodeWithDepth } = {}

    // Initialize all nodes with depth -1
    nodes.forEach((node) => {
        nodeMap[node.nodeId] = { ...node, depth: -1 }
    })

    const assignDepthRecursive = (nodeId: string, currentDepth: number): void => {
        const node = nodeMap[nodeId]
        if (!node) {
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
    // Order nodes by depth
    nodesWithDepth.sort((a, b) => a.depth - b.depth)

    const nodePositions: NodePosition[] = []
    const visited: string[] = []

    const dfs = (nodeId: string, row: number = 0): number => {
        if (visited.includes(nodeId)) {
            return row
        }
        visited.push(nodeId)

        const node = nodesWithDepth.find((n) => n.nodeId === nodeId)
        if (!node) {
            return row
        }

        const nodePosition = {
            ...node,
            position: {
                x: padding + node.depth * HORIZONTAL_SPACING,
                y: padding + row * VERTICAL_SPACING,
            },
        }

        nodePositions.push(nodePosition)

        let maxRow = row
        node.leaf
            .filter((leafId) => !leafId.includes('_joined'))
            .forEach((leafId, index) => {
                dfs(leafId, row + index)
                maxRow = Math.max(maxRow, row + index)
            })

        return maxRow
    }

    let maxRow = 0

    nodesWithDepth.forEach((node) => {
        if (node.depth === 0) {
            maxRow = dfs(node.nodeId, maxRow) + 1
        }
    })

    return nodePositions
}

const calculateTablePosition = (nodePositions: NodePosition[]): Position => {
    // Find the node with the maximum x position
    const farthestNode = nodePositions.reduce((max, node) => (node.position.x > max.position.x ? node : max), {
        position: { x: 0, y: 0 },
    })

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
    // would like to keep nodecanvas logicless
    const { dataWarehouseSavedQueryMapById } = useValues(dataWarehouseViewsLogic)
    const { runDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

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
    }, [nodes, fixedFields, joinedFields])

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
        <div className="w-full h-[100vh]">
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
                            stroke="var(--text-3000)"
                            strokeWidth="2"
                            fill="none"
                        />
                    )
                })}
            </svg>
            {nodePositions.map(({ name, savedQueryId, position, nodeId }, idx) => {
                return (
                    <div
                        key={nodeId}
                        className="absolute"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
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
                            <div className="flex flex-col max-w-full">
                                <div className="flex flex-wrap justify-between gap-2">
                                    <div className="font-bold break-words">{name}</div>
                                    {savedQueryId && (
                                        <LemonButton
                                            type="primary"
                                            size="xsmall"
                                            onClick={() => runDataWarehouseSavedQuery(savedQueryId)}
                                        >
                                            Run
                                        </LemonButton>
                                    )}
                                </div>
                                {savedQueryId && dataWarehouseSavedQueryMapById[savedQueryId]?.status && (
                                    <div className="text-xs mt-2 max-w-full">
                                        <LemonTag
                                            type={
                                                (dataWarehouseSavedQueryMapById[savedQueryId]?.status &&
                                                    StatusTagSetting[
                                                        dataWarehouseSavedQueryMapById[savedQueryId].status as string
                                                    ]) ||
                                                'default'
                                            }
                                            className="break-words"
                                        >
                                            {dataWarehouseSavedQueryMapById[savedQueryId]?.status}
                                        </LemonTag>
                                    </div>
                                )}
                                {savedQueryId && dataWarehouseSavedQueryMapById[savedQueryId]?.last_run_at && (
                                    <span className="text-xs mt-2 max-w-full break-words">
                                        {`Last calculated ${humanFriendlyDetailedTime(
                                            dataWarehouseSavedQueryMapById[savedQueryId]?.last_run_at
                                        )}`}
                                    </span>
                                )}
                            </div>
                        </GenericNode>
                    </div>
                )
            })}

            <div
                className="absolute"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
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
        <div ref={nodeRef} className="w-[500px] bg-bg-3000 border border-black border-2 rounded-lg">
            <TableFields
                fixedFields={fixedFields}
                joinedFields={joinedFields}
                rowsRefs={rowsRefs}
                tableName={tableName}
            />
        </div>
    )
}
