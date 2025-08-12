import { clsx } from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { Edge, Node, NodePosition, NodePositionWithBounds, NodeWithDepth } from './types'

const VERTICAL_SPACING = 300
const HORIZONTAL_SPACING = 400

// Core graph layout calculation functions
const assignDepths = (nodes: Node[]): NodeWithDepth[] => {
    const nodeMap: { [id: string]: NodeWithDepth } = {}

    nodes.forEach((node) => {
        nodeMap[node.nodeId] = { ...node, depth: -1 }
    })

    const assignDepthRecursive = (nodeId: string, currentDepth: number): void => {
        const node = nodeMap[nodeId]
        if (!node) {
            return
        }
        node.depth = currentDepth

        node.leaf.forEach((leafId) => {
            if (nodeMap[leafId]) {
                assignDepthRecursive(leafId, currentDepth + 1)
            }
        })
    }

    nodes.forEach((node) => {
        if (nodeMap[node.nodeId].depth === -1) {
            assignDepthRecursive(node.nodeId, 0)
        }
    })

    return Object.values(nodeMap)
}

const calculateNodePositions = (nodesWithDepth: NodeWithDepth[]): NodePosition[] => {
    const padding = 50
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

const calculateEdges = (nodeRefs: (HTMLDivElement | null)[], nodes: NodePosition[]): Edge[] => {
    const nodes_map = nodes.reduce((acc: Record<string, NodePosition>, node) => {
        acc[node.nodeId] = node
        return acc
    }, {})

    const dfs = (nodeId: string, visited: Set<string> = new Set()): Edge[] => {
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

        for (const leafId of node.leaf) {
            const toNode = nodes_map[leafId]
            const toRef = nodeRefs.find((ref) => ref?.id === leafId)
            if (toNode && toRef) {
                const toWithBounds = calculateBound(toNode, toRef)
                edges.push(...calculateEdgesFromTo(fromWithBounds, toWithBounds))
            }

            edges.push(...dfs(leafId, visited))
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

interface NodeCanvasProps<T extends Node> {
    nodes: T[]
    renderNode: (node: T & NodePosition, ref: (el: HTMLDivElement | null) => void) => JSX.Element
}

export function NodeCanvas<T extends Node>({ nodes, renderNode }: NodeCanvasProps<T>): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [isDragging, setIsDragging] = useState(false)
    const [offset, setOffset] = useState({ x: 0, y: 0 })
    const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
    const nodeRefs = useRef<(HTMLDivElement | null)[]>(Array(nodes.length).fill(null))
    const [nodePositions, setNodePositions] = useState<NodePosition[]>([])
    const [edges, setEdges] = useState<Edge[]>([])

    useEffect(() => {
        const nodesWithDepth = assignDepths(nodes)
        const positions = calculateNodePositions(nodesWithDepth)
        setNodePositions(positions)
    }, [nodes, offset])

    useEffect(() => {
        const allNodes = [...nodePositions]
        const calculatedEdges = calculateEdges([...nodeRefs.current], allNodes)
        setEdges(calculatedEdges)
    }, [nodePositions])

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
        if (!canvas) {
            return
        }

        const ctx = canvas.getContext('2d')
        if (!ctx) {
            return
        }

        const { width, height } = canvas.getBoundingClientRect()
        canvas.width = width
        canvas.height = height
        drawGrid(ctx, width, height)

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
        return () => window.removeEventListener('resize', handleResize)
    }, [offset, nodePositions]) // oxlint-disable-line react-hooks/exhaustive-deps

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
        <div className="w-full h-full relative">
            <canvas
                ref={canvasRef}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
                className={clsx('w-full h-full absolute inset-0', isDragging ? 'cursor-grabbing' : 'cursor-grab')}
            />
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
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
            {nodePositions.map((nodePosition, idx) => (
                <div
                    key={nodePosition.nodeId}
                    className="absolute"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: `${nodePosition.position.x + offset.x}px`,
                        top: `${nodePosition.position.y + offset.y}px`,
                    }}
                >
                    {renderNode(nodePosition as T & NodePosition, (el) => {
                        nodeRefs.current[idx] = el
                        nodeRefs.current[idx]?.setAttribute('id', nodePosition.nodeId)
                    })}
                </div>
            ))}
        </div>
    )
}
