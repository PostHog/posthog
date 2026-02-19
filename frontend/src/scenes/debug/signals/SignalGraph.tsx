import * as d3 from 'd3'
import { useMemo } from 'react'

import { rectEdgePoint, sourceProductColor } from './helpers'
import { GraphEdge, LayoutPosition, NODE_H, NODE_W, SignalNode } from './types'

export function SignalGraph({
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
            onClick={() => {
                if (didDragRef.current) {
                    return
                }
                onSelectSignal(null)
            }}
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
