import { useCallback, useMemo, useRef, useState } from 'react'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
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
const REPULSION = 6000
const SPRING_K = 0.04
const SPRING_LENGTH = 180
const DAMPING = 0.85
const CENTER_GRAVITY = 0.008
const MAX_ITERATIONS = 400
const MIN_SEPARATION = 60

// ── Force-directed layout ──────────────────────────────────────────────────────

function computeLayout(signals: SignalNode[]): { positions: Map<string, LayoutPosition>; edges: GraphEdge[] } {
    if (signals.length === 0) {
        return { positions: new Map(), edges: [] }
    }

    const signalIds = new Set(signals.map((s) => s.signal_id))

    // Build edges from match_metadata
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

    // Initialize positions in a circle
    const nodes = signals.map((s, i) => ({
        id: s.signal_id,
        x: Math.cos((2 * Math.PI * i) / signals.length) * 200 + 500,
        y: Math.sin((2 * Math.PI * i) / signals.length) * 200 + 400,
        vx: 0,
        vy: 0,
    }))

    const nodeMap = new Map(nodes.map((n) => [n.id, n]))

    for (let iter = 0; iter < MAX_ITERATIONS; iter++) {
        // Repulsion between all pairs
        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const a = nodes[i]
                const b = nodes[j]
                const dx = b.x - a.x
                const dy = b.y - a.y
                const dist = Math.max(Math.sqrt(dx * dx + dy * dy), MIN_SEPARATION)
                const force = REPULSION / (dist * dist)
                const fx = (dx / dist) * force
                const fy = (dy / dist) * force
                a.vx -= fx
                a.vy -= fy
                b.vx += fx
                b.vy += fy
            }
        }

        // Spring attraction along edges
        for (const edge of edges) {
            const a = nodeMap.get(edge.source)
            const b = nodeMap.get(edge.target)
            if (!a || !b) {
                continue
            }
            const dx = b.x - a.x
            const dy = b.y - a.y
            const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
            const displacement = dist - SPRING_LENGTH
            const force = SPRING_K * displacement
            const fx = (dx / dist) * force
            const fy = (dy / dist) * force
            a.vx += fx
            a.vy += fy
            b.vx -= fx
            b.vy -= fy
        }

        // Center gravity
        const cx = nodes.reduce((sum, n) => sum + n.x, 0) / nodes.length
        const cy = nodes.reduce((sum, n) => sum + n.y, 0) / nodes.length
        for (const node of nodes) {
            node.vx += (cx - node.x) * CENTER_GRAVITY
            node.vy += (cy - node.y) * CENTER_GRAVITY
        }

        // Damping + update positions
        let totalEnergy = 0
        for (const node of nodes) {
            node.vx *= DAMPING
            node.vy *= DAMPING
            node.x += node.vx
            node.y += node.vy
            totalEnergy += node.vx * node.vx + node.vy * node.vy
        }

        if (totalEnergy < 0.1) {
            break
        }
    }

    // Normalize: find bounding box, add padding, shift so min is at padding
    const PADDING = 100
    let minX = Infinity,
        minY = Infinity,
        maxX = -Infinity,
        maxY = -Infinity
    for (const node of nodes) {
        minX = Math.min(minX, node.x)
        minY = Math.min(minY, node.y)
        maxX = Math.max(maxX, node.x)
        maxY = Math.max(maxY, node.y)
    }

    const positions = new Map<string, LayoutPosition>()
    for (const node of nodes) {
        positions.set(node.id, {
            x: node.x - minX + PADDING,
            y: node.y - minY + PADDING,
        })
    }

    return { positions, edges }
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
}: {
    signals: SignalNode[]
    positions: Map<string, LayoutPosition>
    edges: GraphEdge[]
    selectedSignalId: string | null
    onSelectSignal: (id: string | null) => void
    hoveredEdge: GraphEdge | null
    onHoverEdge: (edge: GraphEdge | null) => void
    onMouseMove: (e: React.MouseEvent) => void
}): JSX.Element {
    const rootIds = useMemo(() => {
        const childIds = new Set(edges.map((e) => e.target))
        return new Set(signals.filter((s) => !childIds.has(s.signal_id)).map((s) => s.signal_id))
    }, [signals, edges])

    // Compute SVG viewport size
    const { svgWidth, svgHeight } = useMemo(() => {
        let maxX = 0,
            maxY = 0
        for (const pos of positions.values()) {
            maxX = Math.max(maxX, pos.x + NODE_W)
            maxY = Math.max(maxY, pos.y + NODE_H)
        }
        return { svgWidth: maxX + 100, svgHeight: maxY + 100 }
    }, [positions])

    const halfW = NODE_W / 2
    const halfH = NODE_H / 2

    return (
        <div className="relative w-full h-full overflow-auto z-0" onMouseMove={onMouseMove}>
            {/* SVG layer for edges */}
            <svg
                className="absolute top-0 left-0 pointer-events-none"
                width={svgWidth}
                height={svgHeight}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ zIndex: 3 }}
            >
                <defs>
                    <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
                        <path d="M0,0 L8,3 L0,6" className="fill-muted" />
                    </marker>
                    <marker id="arrowhead-selected" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
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
            {/* HTML layer for nodes — pointer-events-none on wrapper so edges underneath remain hoverable */}
            <div
                className="absolute top-0 left-0"
                style={{ width: svgWidth, height: svgHeight, zIndex: 2, pointerEvents: 'none' }}
            >
                {signals.map((signal) => {
                    const pos = positions.get(signal.signal_id)
                    if (!pos) {
                        return null
                    }
                    const isSelected = signal.signal_id === selectedSignalId
                    const isRoot = rootIds.has(signal.signal_id)
                    const productColor = sourceProductColor(signal.source_product)
                    return (
                        <div
                            key={signal.signal_id}
                            className={`absolute cursor-pointer select-none rounded transition-shadow ${
                                isSelected ? 'shadow-md' : 'hover:shadow-sm'
                            }`}
                            // Re-enable pointer events on individual nodes
                            // eslint-disable-next-line react/forbid-dom-props
                            data-signal-node
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                left: pos.x,
                                top: pos.y,
                                width: NODE_W,
                                height: NODE_H,
                                border: isSelected ? '2px solid var(--warning)' : '1px solid var(--border)',
                                borderLeftWidth: 3,
                                borderLeftColor: productColor,
                                backgroundColor: 'var(--color-bg-surface-primary)',
                                boxShadow: isSelected ? 'var(--shadow-elevation-3000)' : 'var(--shadow-elevation-3000)',
                                pointerEvents: 'auto',
                            }}
                            onClick={(e) => {
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
            {/* Click on empty space deselects */}
            <div
                className="absolute top-0 left-0"
                style={{ width: svgWidth, height: svgHeight, zIndex: 0, pointerEvents: 'auto' }}
                onClick={() => onSelectSignal(null)}
            />
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

    const { positions, edges } = useMemo(() => computeLayout(signals), [signals])

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
            </div>
        </SceneContent>
    )
}

export default SignalsDebug
