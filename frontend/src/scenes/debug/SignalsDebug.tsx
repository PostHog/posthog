import * as d3 from 'd3'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import api from 'lib/api'
import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

// ── Types ──────────────────────────────────────────────────────────────────────

interface MatchedMetadata {
    parent_signal_id: string
    match_query: string
    reason: string
}

interface NoMatchMetadata {
    reason: string
    rejected_signal_ids: string[]
}

type SignalMatchMetadata = MatchedMetadata | NoMatchMetadata

function isMatchedMetadata(m: SignalMatchMetadata): m is MatchedMetadata {
    return 'parent_signal_id' in m
}

interface SignalNode {
    signal_id: string
    content: string
    source_product: string
    source_type: string
    source_id: string
    weight: number
    timestamp: string
    extra: Record<string, unknown>
    match_metadata?: SignalMatchMetadata | null
}

interface ReportData {
    id: string
    title: string | null
    summary: string | null
    status: string
    total_weight: number
    signal_count: number
    created_at: string | null
    updated_at: string | null
}

interface ReportSignalsResponse {
    report: ReportData | null
    signals: SignalNode[]
}

interface LayoutPosition {
    x: number
    y: number
}

interface GraphEdge {
    source: string
    target: string
    match_query: string
    reason: string
}

// ── Layout constants ───────────────────────────────────────────────────────────

const NODE_W = 152
const NODE_H = 40

// ── Tunable simulation config ──────────────────────────────────────────────────

interface SimConfig {
    repulsion: number
    springK: number
    springLength: number
    damping: number
    centerGravity: number
    collideRadius: number
}

const DEFAULT_CONFIG: SimConfig = {
    repulsion: 500,
    springK: 0.08,
    springLength: 200,
    damping: 0.1,
    centerGravity: 0.035,
    collideRadius: 85,
}

// ── Force simulation types ─────────────────────────────────────────────────────

interface SimNode extends d3.SimulationNodeDatum {
    id: string
}

interface SimEdge extends d3.SimulationLinkDatum<SimNode> {
    match_query: string
    reason: string
}

// ── Live force simulation hook (d3-force powered) ──────────────────────────────

function buildEdges(signals: SignalNode[]): GraphEdge[] {
    const signalIds = new Set(signals.map((s) => s.signal_id))
    const edges: GraphEdge[] = []
    for (const signal of signals) {
        const mm = signal.match_metadata
        if (mm && isMatchedMetadata(mm) && signalIds.has(mm.parent_signal_id)) {
            edges.push({
                source: mm.parent_signal_id,
                target: signal.signal_id,
                match_query: mm.match_query,
                reason: mm.reason,
            })
        }
    }
    return edges
}

function useD3ForceSimulation(
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

// ── Helpers ────────────────────────────────────────────────────────────────────

function sourceProductHue(product: string): number {
    let hash = 0
    for (let i = 0; i < product.length; i++) {
        hash = product.charCodeAt(i) + ((hash << 5) - hash)
    }
    return Math.abs(hash) % 360
}

const SOURCE_PRODUCT_COLORS = [
    'var(--primary)',
    'var(--danger)',
    'var(--warning)',
    'var(--success)',
    'var(--purple)',
    'var(--link)',
] as const

function sourceProductColor(product: string): string {
    return SOURCE_PRODUCT_COLORS[sourceProductHue(product) % SOURCE_PRODUCT_COLORS.length]
}

/** Compute the intersection of a ray from the center of a rectangle to a distant point. */
function rectEdgePoint(
    cx: number,
    cy: number,
    hw: number,
    hh: number,
    targetX: number,
    targetY: number
): { x: number; y: number } {
    const dx = targetX - cx
    const dy = targetY - cy
    if (dx === 0 && dy === 0) {
        return { x: cx + hw, y: cy }
    }
    const absDx = Math.abs(dx) || 0.001
    const absDy = Math.abs(dy) || 0.001
    const tX = hw / absDx
    const tY = hh / absDy
    const t = Math.min(tX, tY)
    return { x: cx + dx * t, y: cy + dy * t }
}

function statusBadgeColor(status: string): string {
    switch (status) {
        case 'ready':
            return 'bg-success-highlight text-success'
        case 'failed':
            return 'bg-danger-highlight text-danger'
        case 'in_progress':
            return 'bg-warning-highlight text-warning'
        case 'pending_input':
            return 'bg-warning-highlight text-warning'
        case 'candidate':
            return 'bg-primary-highlight text-primary'
        default:
            return 'bg-border text-muted'
    }
}

// ── Detail panel ───────────────────────────────────────────────────────────────

function DetailPanel({
    signal,
    isRoot,
    onClose,
}: {
    signal: SignalNode
    isRoot: boolean
    onClose: () => void
}): JSX.Element {
    const panelRef = useRef<HTMLDivElement>(null)
    const [size, setSize] = useState({ width: 420, height: 500 })
    const [position, setPosition] = useState({ x: 16, y: 16 })
    const dragState = useRef<{ startX: number; startY: number; startPosX: number; startPosY: number } | null>(null)
    const resizeState = useRef<{ startX: number; startY: number; startW: number; startH: number } | null>(null)

    // Drag handler
    const onDragMouseDown = useCallback(
        (e: React.MouseEvent) => {
            // Don't start drag if clicking a button
            if ((e.target as HTMLElement).closest('button')) {
                return
            }
            e.preventDefault()
            dragState.current = { startX: e.clientX, startY: e.clientY, startPosX: position.x, startPosY: position.y }
            const onMove = (ev: MouseEvent): void => {
                if (!dragState.current) {
                    return
                }
                const dx = ev.clientX - dragState.current.startX
                const dy = ev.clientY - dragState.current.startY
                setPosition({ x: dragState.current.startPosX - dx, y: dragState.current.startPosY + dy })
            }
            const onUp = (): void => {
                dragState.current = null
                document.removeEventListener('mousemove', onMove)
                document.removeEventListener('mouseup', onUp)
            }
            document.addEventListener('mousemove', onMove)
            document.addEventListener('mouseup', onUp)
        },
        [position]
    )

    // Resize handler (drag from left edge)
    const onResizeMouseDown = useCallback(
        (e: React.MouseEvent) => {
            e.preventDefault()
            e.stopPropagation()
            resizeState.current = { startX: e.clientX, startY: e.clientY, startW: size.width, startH: size.height }
            const onMove = (ev: MouseEvent): void => {
                if (!resizeState.current) {
                    return
                }
                const dx = resizeState.current.startX - ev.clientX
                const dy = ev.clientY - resizeState.current.startY
                setSize({
                    width: Math.max(320, resizeState.current.startW + dx),
                    height: Math.max(300, resizeState.current.startH + dy),
                })
            }
            const onUp = (): void => {
                resizeState.current = null
                document.removeEventListener('mousemove', onMove)
                document.removeEventListener('mouseup', onUp)
            }
            document.addEventListener('mousemove', onMove)
            document.addEventListener('mouseup', onUp)
        },
        [size]
    )

    return (
        <div
            ref={panelRef}
            className="absolute flex flex-col z-20 overflow-hidden rounded-md bg-surface-primary"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: size.width,
                height: size.height,
                right: position.x,
                top: position.y,
                border: '1px solid var(--border)',
                boxShadow: 'var(--shadow-elevation-3000)',
            }}
        >
            {/* Resize handle — left edge */}
            <div
                className="absolute left-0 top-0 bottom-0 cursor-ew-resize z-30 hover:bg-primary/10 transition-colors"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: 5 }}
                onMouseDown={onResizeMouseDown}
            />
            {/* Resize handle — bottom edge */}
            <div
                className="absolute left-0 right-0 bottom-0 cursor-ns-resize z-30 hover:bg-primary/10 transition-colors"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: 5 }}
                onMouseDown={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    const startY = e.clientY
                    const startH = size.height
                    const onMove = (ev: MouseEvent): void => {
                        setSize((s) => ({ ...s, height: Math.max(300, startH + (ev.clientY - startY)) }))
                    }
                    const onUp = (): void => {
                        document.removeEventListener('mousemove', onMove)
                        document.removeEventListener('mouseup', onUp)
                    }
                    document.addEventListener('mousemove', onMove)
                    document.addEventListener('mouseup', onUp)
                }}
            />
            {/* Drag handle — title bar */}
            <div
                className="flex items-center justify-between px-3 py-2 border-b cursor-grab active:cursor-grabbing select-none shrink-0"
                onMouseDown={onDragMouseDown}
            >
                <span className="font-semibold text-[13px]">Signal details</span>
                <LemonButton size="small" onClick={onClose}>
                    ✕
                </LemonButton>
            </div>
            <div className="p-4 space-y-4 text-[13px] overflow-y-auto flex-1">
                <Section label="Signal ID">
                    <code className="text-xs break-all select-all">{signal.signal_id}</code>
                </Section>
                <Section label="Source">
                    <div className="flex items-center gap-1.5">
                        <span
                            className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: sourceProductColor(signal.source_product) }}
                        />
                        <span>
                            {signal.source_product} / {signal.source_type}
                        </span>
                    </div>
                </Section>
                <div className="flex gap-6">
                    <Section label="Weight">{signal.weight}</Section>
                    <Section label="Timestamp">{signal.timestamp}</Section>
                </div>
                {isRoot && (
                    <div className="text-xs font-medium text-primary bg-primary-highlight rounded px-2 py-1 inline-block">
                        Root signal (started this group)
                    </div>
                )}
                <Section label="Description">
                    <div className="whitespace-pre-wrap text-[13px] leading-relaxed rounded p-2.5 border bg-surface-secondary">
                        {signal.content}
                    </div>
                </Section>
                {signal.source_id && (
                    <Section label="Source ID">
                        <code className="text-xs select-all">{signal.source_id}</code>
                    </Section>
                )}
                {signal.extra && Object.keys(signal.extra).length > 0 && (
                    <Section label="Extra metadata">
                        <pre className="text-xs whitespace-pre-wrap rounded p-2.5 border overflow-x-auto bg-surface-secondary">
                            {JSON.stringify(signal.extra, null, 2)}
                        </pre>
                    </Section>
                )}
                {signal.match_metadata && (
                    <Section label="Match metadata">
                        {isMatchedMetadata(signal.match_metadata) ? (
                            <div className="space-y-3 rounded border p-2.5 bg-surface-secondary">
                                <div>
                                    <span className="text-muted text-xs font-medium">Matched to parent</span>
                                    <code className="block text-xs break-all select-all mt-0.5">
                                        {signal.match_metadata.parent_signal_id}
                                    </code>
                                </div>
                                <div className="text-muted text-xs italic">
                                    Hover the arrow to see the match query and reason
                                </div>
                            </div>
                        ) : (
                            <div className="space-y-3 rounded border p-2.5 bg-surface-secondary">
                                <div>
                                    <span className="text-muted text-xs font-medium">Reason (no match)</span>
                                    <div className="text-[13px] mt-0.5">{signal.match_metadata.reason}</div>
                                </div>
                                {signal.match_metadata.rejected_signal_ids.length > 0 && (
                                    <div>
                                        <span className="text-muted text-xs font-medium">
                                            Rejected signals ({signal.match_metadata.rejected_signal_ids.length})
                                        </span>
                                        <div className="mt-0.5 space-y-0.5">
                                            {signal.match_metadata.rejected_signal_ids.map((id) => (
                                                <code key={id} className="block text-xs break-all select-all">
                                                    {id}
                                                </code>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </Section>
                )}
            </div>
        </div>
    )
}

function Section({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div>
            <div className="text-muted text-xs font-semibold uppercase tracking-wide mb-1">{label}</div>
            <div>{children}</div>
        </div>
    )
}

// ── Edge hover tooltip ─────────────────────────────────────────────────────────

function EdgeTooltip({ edge, x, y }: { edge: GraphEdge; x: number; y: number }): JSX.Element {
    return (
        <div
            className="fixed z-50 border rounded-md pointer-events-none text-[13px] bg-surface-primary"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: x + 14,
                top: y - 10,
                maxWidth: 360,
                padding: '8px 12px',
                border: '1px solid var(--border)',
                boxShadow: 'var(--shadow-elevation-3000)',
            }}
        >
            <div className="font-semibold mb-1.5 text-[13px]">Match connection</div>
            <div className="text-muted text-xs font-medium mb-0.5">Query</div>
            <div className="italic mb-2">{edge.match_query}</div>
            <div className="text-muted text-xs font-medium mb-0.5">Reason</div>
            <div>{edge.reason}</div>
        </div>
    )
}

// ── Simulation tuning controls ─────────────────────────────────────────────────

function SimulationControls({
    config,
    onChange,
}: {
    config: SimConfig
    onChange: (config: SimConfig) => void
}): JSX.Element {
    const [collapsed, setCollapsed] = useState(true)

    const sliders: { key: keyof SimConfig; label: string; min: number; max: number; step: number }[] = [
        { key: 'repulsion', label: 'Repulsion', min: 0, max: 1000, step: 10 },
        { key: 'springK', label: 'Spring strength', min: 0, max: 0.16, step: 0.005 },
        { key: 'springLength', label: 'Spring length', min: 0, max: 400, step: 5 },
        { key: 'centerGravity', label: 'Center pull', min: 0, max: 0.07, step: 0.001 },
        { key: 'damping', label: 'Damping', min: 0, max: 1, step: 0.01 },
        { key: 'collideRadius', label: 'Collide radius', min: 0, max: 170, step: 5 },
    ]

    return (
        <div
            className="absolute bottom-3 right-3 z-20 rounded-md bg-surface-primary text-[13px] select-none"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                border: '1px solid var(--border)',
                boxShadow: 'var(--shadow-elevation-3000)',
                width: collapsed ? 'auto' : 260,
            }}
        >
            <div
                className="flex items-center justify-between px-3 py-1.5 cursor-pointer gap-2"
                onClick={() => setCollapsed((c) => !c)}
            >
                <span className="font-semibold text-xs text-muted uppercase tracking-wide">Physics</span>
                <span className="text-muted text-xs">{collapsed ? '▲' : '▼'}</span>
            </div>
            {!collapsed && (
                <div className="px-3 pb-3 space-y-3 border-t pt-2">
                    {sliders.map(({ key, label, min, max, step }) => (
                        <div key={key}>
                            <div className="flex justify-between text-xs mb-1">
                                <span className="text-muted">{label}</span>
                                <span className="font-mono tabular-nums">
                                    {config[key] % 1 === 0 ? config[key] : config[key].toFixed(step < 0.01 ? 3 : 2)}
                                </span>
                            </div>
                            <LemonSlider
                                min={min}
                                max={max}
                                step={step}
                                value={config[key]}
                                onChange={(v) => onChange({ ...config, [key]: v })}
                            />
                        </div>
                    ))}
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        fullWidth
                        center
                        onClick={() => onChange({ ...DEFAULT_CONFIG })}
                    >
                        Reset defaults
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

// ── Graph canvas ───────────────────────────────────────────────────────────────

function SignalGraph({
    signals,
    positions,
    edges,
    selectedSignalId,
    onSelectSignal,
    hoveredEdge,
    onHoverEdge,
    onMouseMove,
    containerRef,
    onNodeDragStart,
    draggedNodeId,
    didDragRef,
    transform,
}: {
    signals: SignalNode[]
    positions: Map<string, LayoutPosition>
    edges: GraphEdge[]
    selectedSignalId: string | null
    onSelectSignal: (id: string | null) => void
    hoveredEdge: GraphEdge | null
    onHoverEdge: (edge: GraphEdge | null) => void
    onMouseMove: (e: React.MouseEvent) => void
    containerRef: (node: HTMLDivElement | null) => void
    onNodeDragStart: (signalId: string, e: React.MouseEvent) => void
    draggedNodeId: string | null
    didDragRef: React.RefObject<boolean>
    transform: d3.ZoomTransform
}): JSX.Element {
    const rootIds = useMemo(() => {
        const childIds = new Set(edges.map((e) => e.target))
        return new Set(signals.filter((s) => !childIds.has(s.signal_id)).map((s) => s.signal_id))
    }, [signals, edges])

    const halfW = NODE_W / 2
    const halfH = NODE_H / 2

    return (
        <div
            ref={containerRef}
            className="relative w-full h-full overflow-hidden z-0"
            onMouseMove={onMouseMove}
            onClick={() => onSelectSignal(null)}
        >
            {/* Zoom-transformed wrapper — infinite canvas via overflow:visible */}
            <div
                style={{
                    transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.k})`,
                    transformOrigin: '0 0',
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: 1,
                    height: 1,
                    overflow: 'visible',
                }}
            >
                {/* SVG layer for edges — overflow:visible so lines render at any coordinate */}
                <svg
                    className="absolute top-0 left-0 pointer-events-none"
                    width={1}
                    height={1}
                    overflow="visible"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ zIndex: 3 }}
                >
                    <defs>
                        <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
                            <path d="M0,0 L8,3 L0,6" className="fill-muted" />
                        </marker>
                        <marker
                            id="arrowhead-selected"
                            markerWidth="8"
                            markerHeight="6"
                            refX="7"
                            refY="3"
                            orient="auto"
                        >
                            <path d="M0,0 L8,3 L0,6" fill="var(--warning)" />
                        </marker>
                    </defs>
                    {edges.map((edge) => {
                        const sp = positions.get(edge.source)
                        const tp = positions.get(edge.target)
                        if (!sp || !tp) {
                            return null
                        }
                        // Arrow points from child (target) back to parent (source)
                        const tCx = tp.x + halfW
                        const tCy = tp.y + halfH
                        const sCx = sp.x + halfW
                        const sCy = sp.y + halfH
                        const start = rectEdgePoint(tCx, tCy, halfW + 4, halfH + 4, sCx, sCy)
                        const end = rectEdgePoint(sCx, sCy, halfW + 4, halfH + 4, tCx, tCy)
                        const isHovered = hoveredEdge === edge
                        const isSelectedEdge =
                            selectedSignalId !== null &&
                            (edge.source === selectedSignalId || edge.target === selectedSignalId)
                        const isHighlighted = isHovered || isSelectedEdge
                        const key = `${edge.source}-${edge.target}`
                        return (
                            <g key={key}>
                                <line
                                    x1={start.x}
                                    y1={start.y}
                                    x2={end.x}
                                    y2={end.y}
                                    stroke={isHighlighted ? 'var(--warning)' : 'var(--border)'}
                                    strokeWidth={isHighlighted ? 2 : 1.5}
                                    markerEnd={isHighlighted ? 'url(#arrowhead-selected)' : 'url(#arrowhead)'}
                                    opacity={isHighlighted ? 1 : 0.6}
                                />
                                {/* Invisible wider hit area for hover */}
                                <line
                                    x1={start.x}
                                    y1={start.y}
                                    x2={end.x}
                                    y2={end.y}
                                    stroke="transparent"
                                    strokeWidth={14}
                                    className="pointer-events-auto cursor-pointer"
                                    onMouseEnter={() => onHoverEdge(edge)}
                                    onMouseLeave={() => onHoverEdge(null)}
                                />
                            </g>
                        )
                    })}
                </svg>
                {/* HTML layer for nodes — overflow:visible for infinite canvas */}
                <div
                    className="absolute top-0 left-0"
                    style={{ width: 1, height: 1, overflow: 'visible', zIndex: 2, pointerEvents: 'none' }}
                >
                    {signals.map((signal) => {
                        const pos = positions.get(signal.signal_id)
                        if (!pos) {
                            return null
                        }
                        const isSelected = signal.signal_id === selectedSignalId
                        const isDragged = signal.signal_id === draggedNodeId
                        const isRoot = rootIds.has(signal.signal_id)
                        const productColor = sourceProductColor(signal.source_product)
                        return (
                            <div
                                key={signal.signal_id}
                                className={`absolute select-none rounded transition-shadow ${
                                    isDragged
                                        ? 'cursor-grabbing shadow-lg'
                                        : isSelected
                                          ? 'cursor-grab shadow-md'
                                          : 'cursor-grab hover:shadow-sm'
                                }`}
                                // eslint-disable-next-line react/forbid-dom-props
                                data-signal-node
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    left: pos.x,
                                    top: pos.y,
                                    width: NODE_W,
                                    height: NODE_H,
                                    borderTop: isSelected ? '2px solid var(--warning)' : '1px solid var(--border)',
                                    borderRight: isSelected ? '2px solid var(--warning)' : '1px solid var(--border)',
                                    borderBottom: isSelected ? '2px solid var(--warning)' : '1px solid var(--border)',
                                    borderLeft: `3px solid ${productColor}`,
                                    backgroundColor: 'var(--color-bg-surface-primary)',
                                    boxShadow: isSelected
                                        ? 'var(--shadow-elevation-3000)'
                                        : 'var(--shadow-elevation-3000)',
                                    pointerEvents: 'auto',
                                }}
                                onMouseDown={(e) => {
                                    // Left button only
                                    if (e.button !== 0) {
                                        return
                                    }
                                    onNodeDragStart(signal.signal_id, e)
                                }}
                                onClick={(e) => {
                                    // Only fire select if this wasn't a drag
                                    if (didDragRef.current) {
                                        return
                                    }
                                    e.stopPropagation()
                                    onSelectSignal(isSelected ? null : signal.signal_id)
                                }}
                                title={signal.content.slice(0, 200)}
                            >
                                <div className="flex items-center h-full px-2.5 gap-2 overflow-hidden">
                                    {isRoot && (
                                        <span
                                            className="shrink-0 w-2 h-2 rounded-full border"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ backgroundColor: productColor, borderColor: productColor }}
                                        />
                                    )}
                                    <div className="truncate leading-snug">
                                        <div className="font-medium text-[13px] truncate">{signal.source_type}</div>
                                        <div className="text-muted truncate text-xs">
                                            {signal.source_product}
                                            {signal.weight !== undefined ? ` · w${signal.weight}` : ''}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function SignalsDebug(): JSX.Element {
    const [reportId, setReportId] = useState('')
    const [loading, setLoading] = useState(false)
    const [report, setReport] = useState<ReportData | null>(null)
    const [signals, setSignals] = useState<SignalNode[]>([])
    const [loaded, setLoaded] = useState(false)
    const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null)
    const [hoveredEdge, setHoveredEdge] = useState<GraphEdge | null>(null)
    const [mousePos, setMousePos] = useState({ x: 0, y: 0 })
    const [simConfig, setSimConfig] = useLocalStorage<SimConfig>('signals-debug-physics', { ...DEFAULT_CONFIG })

    const {
        positions,
        edges,
        containerRef,
        onNodeDragStart,
        draggedNodeId,
        didDragRef,
        transform,
        viewportCenter,
        resetView,
    } = useD3ForceSimulation(signals, simConfig)

    const rootIds = useMemo(() => {
        const childIds = new Set(edges.map((e) => e.target))
        return new Set(signals.filter((s) => !childIds.has(s.signal_id)).map((s) => s.signal_id))
    }, [signals, edges])

    const selectedSignal = useMemo(
        () => (selectedSignalId ? (signals.find((s) => s.signal_id === selectedSignalId) ?? null) : null),
        [signals, selectedSignalId]
    )

    const handleLoad = useCallback(async () => {
        const trimmed = reportId.trim()
        if (!trimmed) {
            return
        }
        setLoading(true)
        setSelectedSignalId(null)
        setHoveredEdge(null)
        try {
            const response = await api.get<ReportSignalsResponse>(
                `api/environments/@current/signals/report_signals/?report_id=${encodeURIComponent(trimmed)}`
            )
            setReport(response.report)
            setSignals(response.signals)
            setLoaded(true)
            if (response.signals.length === 0) {
                lemonToast.info('No signals found for this report')
            }
        } catch (error) {
            lemonToast.error(`Failed to load signals: ${error}`)
        } finally {
            setLoading(false)
        }
    }, [reportId])

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key === 'Enter') {
                void handleLoad()
            }
        },
        [handleLoad]
    )

    const handleMouseMove = useCallback((e: React.MouseEvent) => {
        setMousePos({ x: e.clientX, y: e.clientY })
    }, [])

    return (
        <SceneContent className="h-full flex flex-col grow">
            {/* Header */}
            <div className="shrink-0 space-y-2 pb-3">
                <h1 className="text-xl font-bold">Signal report explorer</h1>
                <div className="flex gap-2 items-center max-w-2xl">
                    <LemonInput
                        fullWidth
                        value={reportId}
                        onChange={setReportId}
                        onKeyDown={handleKeyDown}
                        placeholder="Enter report UUID..."
                        className="font-mono"
                    />
                    <LemonButton type="primary" onClick={handleLoad} loading={loading} disabled={!reportId.trim()}>
                        Load
                    </LemonButton>
                </div>
                {/* Report summary bar */}
                {report && (
                    <div className="flex items-center gap-3 text-sm bg-surface-secondary border rounded px-3 py-2 max-w-4xl">
                        <span
                            className={`text-xs font-medium rounded px-1.5 py-0.5 ${statusBadgeColor(report.status)}`}
                        >
                            {report.status}
                        </span>
                        {report.title && <span className="font-medium truncate">{report.title}</span>}
                        <span className="text-muted text-xs shrink-0">
                            {signals.length} signal{signals.length !== 1 ? 's' : ''} · weight{' '}
                            {report.total_weight.toFixed(2)}
                        </span>
                    </div>
                )}
            </div>

            {/* Graph area — fills remaining viewport */}
            <div className="relative grow border rounded bg-surface-primary overflow-hidden">
                {loading && (
                    <div className="absolute inset-0 flex items-center justify-center z-30">
                        <Spinner />
                    </div>
                )}
                {!loaded && !loading && (
                    <div className="flex items-center justify-center h-full text-muted text-sm">
                        Enter a report UUID above to explore its signal graph
                    </div>
                )}
                {loaded && signals.length === 0 && !loading && (
                    <div className="flex items-center justify-center h-full text-muted text-sm">
                        No signals found for this report
                    </div>
                )}
                {loaded && signals.length > 0 && (
                    <SignalGraph
                        signals={signals}
                        positions={positions}
                        edges={edges}
                        selectedSignalId={selectedSignalId}
                        onSelectSignal={setSelectedSignalId}
                        hoveredEdge={hoveredEdge}
                        onHoverEdge={setHoveredEdge}
                        onMouseMove={handleMouseMove}
                        containerRef={containerRef}
                        onNodeDragStart={onNodeDragStart}
                        draggedNodeId={draggedNodeId}
                        didDragRef={didDragRef}
                        transform={transform}
                    />
                )}
                {/* Detail panel */}
                {selectedSignal && (
                    <DetailPanel
                        signal={selectedSignal}
                        isRoot={rootIds.has(selectedSignal.signal_id)}
                        onClose={() => setSelectedSignalId(null)}
                    />
                )}
                {/* Edge hover tooltip */}
                {hoveredEdge && <EdgeTooltip edge={hoveredEdge} x={mousePos.x} y={mousePos.y} />}
                {/* Zoom level & viewport center indicator */}
                {loaded && signals.length > 0 && (
                    <div
                        className="absolute bottom-3 left-3 z-20 flex items-center gap-1.5 rounded-md bg-surface-primary text-xs text-muted font-mono tabular-nums select-none"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            border: '1px solid var(--border)',
                            padding: '4px 8px',
                        }}
                    >
                        <span>{Math.round(transform.k * 100)}%</span>
                        <span className="opacity-40">·</span>
                        <span>
                            {viewportCenter.x}, {viewportCenter.y}
                        </span>
                        <LemonButton size="xsmall" type="tertiary" onClick={resetView} className="ml-1">
                            Reset
                        </LemonButton>
                    </div>
                )}
                {/* Physics tuning panel */}
                {loaded && signals.length > 0 && <SimulationControls config={simConfig} onChange={setSimConfig} />}
            </div>
        </SceneContent>
    )
}

export default SignalsDebug
