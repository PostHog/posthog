import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import GenericNode from './Node'
import { TableFields } from './TableFields'

interface Position {
    x: number
    y: number
}

interface NodePosition {
    id: string
    name: string
    position: Position
    leaf: string[]
}

interface Edge {
    from: Position
    to: Position
}

interface NodePositionWithBounds extends NodePosition {
    left: Position | null
    right: Position | null
}

const calculateNodePositions = (): NodePosition[] => {
    const windowWidth = window.innerWidth
    const windowHeight = window.innerHeight
    const padding = 50
    const verticalSpacing = 150
    const horizontalSpacing = 300

    const nodes: NodePosition[] = [
        {
            id: 'posthog',
            name: 'PostHog',
            position: { x: padding, y: padding },
            leaf: ['schema'],
        },
        {
            id: 'stripe',
            name: 'Stripe',
            position: { x: padding, y: padding + verticalSpacing },
            leaf: ['stripe-invoice', 'stripe-customer', 'stripe-account'],
        },
        {
            id: 'stripe-invoice',
            name: 'Stripe invoice',
            position: { x: padding + horizontalSpacing, y: padding + verticalSpacing },
            leaf: ['tax_code'],
        },
        {
            id: 'stripe-account',
            name: 'Stripe account',
            position: { x: padding + horizontalSpacing, y: padding + 2 * verticalSpacing },
            leaf: ['account_size', 'customer_email'],
        },
    ]

    nodes.forEach((node) => {
        node.position.x = Math.min(node.position.x, windowWidth - padding)
        node.position.y = Math.min(node.position.y, windowHeight - padding)
    })

    return nodes
}

const NODES: NodePosition[] = calculateNodePositions()

const TABLE_POSITION = { x: Math.min(700, window.innerWidth - 300), y: 100 }

const calculateEdges = (nodeRefs: (HTMLDivElement | null)[], nodes: NodePosition[]): Edge[] => {
    const nodes_map = nodes.reduce((acc: Record<string, NodePosition>, node) => {
        acc[node.id] = node
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
                const newEdges = calculateEdgesFromTo(fromWithBounds, toWithBounds, depth)
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
        if (!visited.has(node.id)) {
            edges.push(...dfs(node.id, visited))
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

const calculateEdgesFromTo = (from: NodePositionWithBounds, to: NodePositionWithBounds, depth = 0): Edge[] => {
    if (!from.right || !to.left) {
        return []
    }

    const edges = []
    const spacing = 25 + 25 * depth
    if (from.right.y != to.left.y) {
        edges.push({
            from: from.right,
            to: { x: to.left.x - spacing, y: from.right.y },
        })
        edges.push({
            from: { x: to.left.x - spacing, y: from.right.y },
            to: { x: to.left.x - spacing, y: to.left.y },
        })
        edges.push({
            from: { x: to.left.x - spacing, y: to.left.y },
            to: to.left,
        })
    } else {
        edges.push({
            from: from.right,
            to: to.left,
        })
    }

    return edges
}

const ScrollableDraggableCanvas = (): JSX.Element => {
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [isDragging, setIsDragging] = useState(false)
    const [offset, setOffset] = useState({ x: 0, y: 0 })
    const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
    const rowsRefs = useRef<(HTMLDivElement | null)[]>(Array(FAKE_JOINED_DATA.length).fill(null))
    const nodeRefs = useRef<(HTMLDivElement | null)[]>(Array(NODES.length).fill(null))
    const tableNodeRef = useRef<HTMLDivElement | null>(null)

    const drawGrid = (ctx: CanvasRenderingContext2D, canvasWidth: number, canvasHeight: number): void => {
        ctx.fillStyle = '#000000'
        const dotSize = 1
        const spacing = 20

        for (let x = offset.x % spacing; x < canvasWidth; x += spacing) {
            for (let y = offset.y % spacing; y < canvasHeight; y += spacing) {
                ctx.fillRect(x, y, dotSize, dotSize)
            }
        }

        const allNodes = [...NODES]
        // calculated table row positions
        rowsRefs.current.forEach((ref) => {
            const rect = ref?.getBoundingClientRect()
            const nodeRect = tableNodeRef.current?.getBoundingClientRect()

            if (!rect) {
                return
            }

            if (nodeRect && ref) {
                allNodes.push({
                    id: ref.id,
                    name: 'Table',
                    position: { x: TABLE_POSITION.x, y: TABLE_POSITION.y + (rect.y - nodeRect.y) },
                    leaf: [],
                })
            }
        })

        const edges = calculateEdges([...nodeRefs.current, ...rowsRefs.current], allNodes)

        ctx.globalCompositeOperation = 'xor'

        // Draw node edges. Offset translates original position to scrolled/dragged position
        edges.forEach(({ from, to }) => {
            ctx.beginPath()
            ctx.moveTo(from.x + offset.x, from.y + offset.y)
            ctx.lineTo(to.x + offset.x, to.y + offset.y)
            ctx.strokeStyle = 'black'
            ctx.lineWidth = 1
            ctx.stroke()
        })
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
    }, [offset])

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
            {NODES.map(({ name, position, id }, idx) => {
                return (
                    <div
                        key={id}
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
                                nodeRefs.current[idx]?.setAttribute('id', id)
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
                    left: `${TABLE_POSITION.x + offset.x}px`,
                    top: `${TABLE_POSITION.y + offset.y}px`,
                }}
            >
                <TableFieldNode nodeRef={tableNodeRef} rowsRefs={rowsRefs} />
            </div>
        </div>
    )
}

export default ScrollableDraggableCanvas

const FAKE_JOINED_DATA = [
    { name: 'customer_email', type: 'string', table: 'prod_stripe_invoice' },
    { name: 'account_size', type: 'string', table: 'prod_stripe_invoice' },
    { name: 'tax_code', type: 'string', table: 'prod_stripe_customer' },
    { name: 'location', type: 'string', table: 'prod_stripe_account' },
]

interface TableFieldNodeProps {
    rowsRefs: React.MutableRefObject<(HTMLDivElement | null)[]>
    nodeRef: React.MutableRefObject<HTMLDivElement | null>
}

function TableFieldNode({ nodeRef, rowsRefs }: TableFieldNodeProps): JSX.Element {
    return (
        <div ref={nodeRef} className="w-[500px] h-[600px] bg-white border border-black border-2 rounded-lg">
            <TableFields joinedData={FAKE_JOINED_DATA} rowsRefs={rowsRefs} />
        </div>
    )
}
