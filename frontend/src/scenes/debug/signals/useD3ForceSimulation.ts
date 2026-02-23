import * as d3 from 'd3'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { buildEdges } from './helpers'
import { GraphEdge, LayoutPosition, SignalNode, SimConfig, SimEdge, SimNode } from './types'

// ── Live force simulation hook (d3-force powered) ──────────────────────────────

export function useD3ForceSimulation(
    signals: SignalNode[],
    config: SimConfig
): {
    positions: Map<string, LayoutPosition>
    edges: GraphEdge[]
    containerRef: (node: HTMLDivElement | null) => void
    onNodeDragStart: (signalId: string, e: React.MouseEvent) => void
    draggedNodeId: string | null
    didDragRef: React.RefObject<boolean>
    transform: d3.ZoomTransform
    viewportCenter: { x: number; y: number }
    resetView: () => void
} {
    const simulationRef = useRef<d3.Simulation<SimNode, SimEdge> | null>(null)
    const nodesRef = useRef<SimNode[]>([])
    const nodeMapRef = useRef<Map<string, SimNode>>(new Map())
    const edgesRef = useRef<GraphEdge[]>([])
    const containerElRef = useRef<HTMLDivElement | null>(null)
    const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null)
    const containerRef = useCallback((node: HTMLDivElement | null) => {
        containerElRef.current = node
        setContainerEl(node)
    }, [])

    const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null)
    const didDragRef = useRef(false)
    const [tick, setTick] = useState(0)
    const transformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity)
    const [transform, setTransform] = useState<d3.ZoomTransform>(d3.zoomIdentity)
    const zoomRef = useRef<d3.ZoomBehavior<HTMLDivElement, unknown> | null>(null)
    const configRef = useRef<SimConfig>(config)
    configRef.current = config

    // Snapshot positions from simulation nodes for React consumption
    const positions = useMemo(() => {
        void tick // depend on tick
        const map = new Map<string, LayoutPosition>()
        for (const node of nodesRef.current) {
            map.set(node.id, { x: node.x ?? 0, y: node.y ?? 0 })
        }
        return map
    }, [tick])

    const edges = useMemo(() => {
        void tick
        return edgesRef.current
    }, [tick])

    // Create simulation once
    useEffect(() => {
        const sim = d3
            .forceSimulation<SimNode, SimEdge>()
            .force('charge', d3.forceManyBody<SimNode>().strength(-config.repulsion))
            .force(
                'link',
                d3
                    .forceLink<SimNode, SimEdge>()
                    .id((d) => d.id)
                    .distance(config.springLength)
                    .strength(config.springK)
            )
            // Gentle pull toward canvas origin (0,0)
            .force('x', d3.forceX<SimNode>(0).strength(config.centerGravity))
            .force('y', d3.forceY<SimNode>(0).strength(config.centerGravity))
            .force('collide', d3.forceCollide<SimNode>(config.collideRadius))
            .velocityDecay(config.damping)
            .on('tick', () => {
                setTick((t) => t + 1)
            })

        sim.stop() // don't run until we have data
        simulationRef.current = sim

        return () => {
            sim.stop()
            simulationRef.current = null
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // Update forces live when config changes
    useEffect(() => {
        const sim = simulationRef.current
        if (!sim) {
            return
        }

        ;(sim.force('charge') as d3.ForceManyBody<SimNode>).strength(-config.repulsion)

        const linkForce = sim.force('link') as d3.ForceLink<SimNode, SimEdge>
        linkForce.distance(config.springLength).strength(config.springK)
        ;(sim.force('x') as d3.ForceX<SimNode>).strength(config.centerGravity)
        ;(sim.force('y') as d3.ForceY<SimNode>).strength(config.centerGravity)
        ;(sim.force('collide') as d3.ForceCollide<SimNode>).radius(config.collideRadius)

        sim.velocityDecay(config.damping)

        // Reheat so the changes take effect
        sim.alpha(0.5).restart()
    }, [config])

    // Setup d3-zoom on the container — infinite canvas, click-drag to pan
    // Runs when containerEl becomes available (i.e. when SignalGraph mounts)
    useEffect(() => {
        if (!containerEl) {
            return
        }

        const zoom = d3
            .zoom<HTMLDivElement, unknown>()
            .scaleExtent([0.05, 6])
            // No translateExtent — infinite canvas
            .filter((event: Event) => {
                // Don't initiate zoom/pan when clicking/dragging on a node
                if ((event.target as HTMLElement).closest('[data-signal-node]')) {
                    // Allow wheel events on nodes (for zooming while cursor is over a node)
                    return event.type === 'wheel'
                }
                return true
            })
            .on('zoom', (event: d3.D3ZoomEvent<HTMLDivElement, unknown>) => {
                transformRef.current = event.transform
                setTransform(event.transform)
            })

        zoomRef.current = zoom
        d3.select(containerEl).call(zoom)

        // Center the origin (0,0) in the middle of the viewport
        const rect = containerEl.getBoundingClientRect()
        const initialTransform = d3.zoomIdentity.translate(rect.width / 2, rect.height / 2)
        d3.select(containerEl).call(zoom.transform, initialTransform)

        return () => {
            d3.select(containerEl).on('.zoom', null)
            zoomRef.current = null
        }
    }, [containerEl])

    // Initialize / re-initialize when signals change
    useEffect(() => {
        const sim = simulationRef.current
        if (!sim) {
            return
        }

        if (signals.length === 0) {
            nodesRef.current = []
            nodeMapRef.current = new Map()
            edgesRef.current = []
            sim.nodes([])
            ;(sim.force('link') as d3.ForceLink<SimNode, SimEdge>).links([])
            sim.stop()
            setTick((t) => t + 1)
            return
        }

        const oldMap = nodeMapRef.current
        const newNodes: SimNode[] = signals.map((s, i) => {
            const existing = oldMap.get(s.signal_id)
            if (existing) {
                // Preserve position, clear velocity for a smooth re-settle
                return { ...existing, vx: 0, vy: 0 }
            }
            // Arrange new nodes in a circle around origin
            return {
                id: s.signal_id,
                x: Math.cos((2 * Math.PI * i) / signals.length) * 200,
                y: Math.sin((2 * Math.PI * i) / signals.length) * 200,
                vx: 0,
                vy: 0,
            }
        })

        const graphEdges = buildEdges(signals)
        const simEdges: SimEdge[] = graphEdges.map((e) => ({
            source: e.source,
            target: e.target,
            match_query: e.match_query,
            reason: e.reason,
        }))

        nodesRef.current = newNodes
        nodeMapRef.current = new Map(newNodes.map((n) => [n.id, n]))
        edgesRef.current = graphEdges

        sim.nodes(newNodes)
        ;(sim.force('link') as d3.ForceLink<SimNode, SimEdge>).links(simEdges)
        sim.alpha(1).restart()
    }, [signals])

    // Drag handler — uses d3-force fx/fy pinning
    const onNodeDragStart = useCallback(
        (signalId: string, e: React.MouseEvent) => {
            e.preventDefault()
            e.stopPropagation()

            const sim = simulationRef.current
            const container = containerElRef.current
            if (!sim || !container) {
                return
            }

            const node = nodeMapRef.current.get(signalId)
            if (!node) {
                return
            }

            const rect = container.getBoundingClientRect()
            const t = transformRef.current

            // Convert screen coords to graph space (accounting for zoom transform)
            const graphX = (e.clientX - rect.left - t.x) / t.k
            const graphY = (e.clientY - rect.top - t.y) / t.k

            const offsetX = graphX - (node.x ?? 0)
            const offsetY = graphY - (node.y ?? 0)

            // Pin node and reheat simulation
            node.fx = node.x
            node.fy = node.y
            sim.alphaTarget(0.3).restart()

            didDragRef.current = false
            setDraggedNodeId(signalId)

            const onMove = (ev: MouseEvent): void => {
                const r = container.getBoundingClientRect()
                const ct = transformRef.current
                const gx = (ev.clientX - r.left - ct.x) / ct.k
                const gy = (ev.clientY - r.top - ct.y) / ct.k
                node.fx = gx - offsetX
                node.fy = gy - offsetY
                didDragRef.current = true
            }

            const onUp = (): void => {
                // Unpin node and let it settle
                node.fx = null
                node.fy = null
                sim.alphaTarget(0)
                setDraggedNodeId(null)
                document.removeEventListener('mousemove', onMove)
                document.removeEventListener('mouseup', onUp)
            }

            document.addEventListener('mousemove', onMove)
            document.addEventListener('mouseup', onUp)
        },
        [] // no deps needed — everything is via refs
    )

    const resetView = useCallback(() => {
        const container = containerElRef.current
        const zoom = zoomRef.current
        if (!container || !zoom) {
            return
        }
        const rect = container.getBoundingClientRect()
        const resetTransform = d3.zoomIdentity.translate(rect.width / 2, rect.height / 2)
        d3.select(container).transition().duration(300).call(zoom.transform, resetTransform)
    }, [])

    const viewportCenter = useMemo(() => {
        const el = containerElRef.current
        if (!el) {
            return { x: 0, y: 0 }
        }
        const rect = el.getBoundingClientRect()
        return {
            x: Math.round((rect.width / 2 - transform.x) / transform.k),
            y: Math.round((rect.height / 2 - transform.y) / transform.k),
        }
    }, [transform])

    return {
        positions,
        edges,
        containerRef,
        onNodeDragStart,
        draggedNodeId,
        didDragRef,
        transform,
        viewportCenter,
        resetView,
    }
}
