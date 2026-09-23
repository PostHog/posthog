import React, { useCallback, useMemo, useRef } from 'react'

import { useLatest } from '../../core/hooks/useLatest'
import { useTooltipLifecycle } from '../../core/hooks/useTooltipLifecycle'
import type { Series, TooltipContext } from '../../core/types'
import { hitToHoverIndex, hoverIndexToHit, sankeyHitAt } from './sankey-data'
import type { SankeyChartLayout, SankeyHit, SankeyLinkDatum, SankeyNodeDatum } from './sankey-data'
import type { SankeyTooltipContext, SankeyTooltipHit } from './types'

interface UseSankeyInteractionOptions<NodeMeta, LinkMeta> {
    layout: SankeyChartLayout<NodeMeta, LinkMeta>
    canvasRef: React.RefObject<HTMLCanvasElement>
    wrapperRef: React.RefObject<HTMLDivElement>
    showTooltip: boolean
    onNodeClick?: (node: SankeyNodeDatum<NodeMeta>) => void
    onLinkClick?: (link: SankeyLinkDatum<NodeMeta, LinkMeta>) => void
}

interface UseSankeyInteractionResult<NodeMeta, LinkMeta> {
    hoverIndex: number
    hoverPosition: { x: number; y: number } | null
    tooltipCtx: SankeyTooltipContext<NodeMeta, LinkMeta> | null
    handlers: {
        onMouseMove: (e: React.MouseEvent<HTMLDivElement>) => void
        onMouseLeave: () => void
        onClick: (e: React.MouseEvent<HTMLDivElement>) => void
        onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void
    }
}

function resolveHit<NodeMeta, LinkMeta>(
    layout: SankeyChartLayout<NodeMeta, LinkMeta>,
    hit: SankeyHit
): SankeyTooltipHit<NodeMeta, LinkMeta> {
    return hit.kind === 'node'
        ? { kind: 'node', node: layout.nodes[hit.index] }
        : { kind: 'link', link: layout.links[hit.index] }
}

function buildTooltipCtx<NodeMeta, LinkMeta>(
    layout: SankeyChartLayout<NodeMeta, LinkMeta>,
    hit: SankeyHit,
    cursor: { x: number; y: number } | null,
    canvasBounds: DOMRect
): SankeyTooltipContext<NodeMeta, LinkMeta> {
    const resolved = resolveHit(layout, hit)
    const label =
        resolved.kind === 'node' ? resolved.node.label : `${resolved.link.source.label} → ${resolved.link.target.label}`
    const value = resolved.kind === 'node' ? resolved.node.value : resolved.link.value
    const color = resolved.kind === 'node' ? resolved.node.color : resolved.link.color
    const meta: NodeMeta | LinkMeta | undefined = resolved.kind === 'node' ? resolved.node.meta : resolved.link.meta
    const anchor =
        resolved.kind === 'node'
            ? { x: resolved.node.x1, y: (resolved.node.y0 + resolved.node.y1) / 2 }
            : {
                  x: (resolved.link.source.x1 + resolved.link.target.x0) / 2,
                  y: (resolved.link.y0 + resolved.link.y1) / 2,
              }
    // One synthetic series row keeps the shared tooltip plumbing (equivalence checks, the
    // default renderer fallback) working on a chart that has no series.
    const series: Series<NodeMeta | LinkMeta> = { key: `${hit.kind}:${hit.index}`, label, data: [value], color, meta }
    return {
        dataIndex: hitToHoverIndex(layout, hit),
        label,
        seriesData: [{ series, value, color }],
        position: anchor,
        hoverPosition: cursor,
        canvasBounds,
        isPinned: false,
        hit: resolved,
        total: layout.total,
    }
}

export function useSankeyInteraction<NodeMeta = unknown, LinkMeta = NodeMeta>({
    layout,
    canvasRef,
    wrapperRef,
    showTooltip,
    onNodeClick,
    onLinkClick,
}: UseSankeyInteractionOptions<NodeMeta, LinkMeta>): UseSankeyInteractionResult<NodeMeta, LinkMeta> {
    type Ctx = SankeyTooltipContext<NodeMeta, LinkMeta>
    const layoutRef = useLatest(layout)

    const rebuildPinnedCtx = useCallback(
        (prev: TooltipContext<NodeMeta | LinkMeta>): Ctx | null => {
            const hit = hoverIndexToHit(layoutRef.current, prev.dataIndex)
            if (!hit) {
                return null
            }
            const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
            return buildTooltipCtx(layoutRef.current, hit, prev.hoverPosition, canvasBounds)
        },
        [layoutRef, canvasRef]
    )

    const { hoverIndex, hoverPosition, tooltipCtx, setHover, setTooltipCtx, clearTooltip } = useTooltipLifecycle<
        NodeMeta | LinkMeta
    >({
        wrapperRef,
        rebuildPinnedCtx,
        rebuildDeps: [layout],
    })

    const hoverIndexRef = useLatest(hoverIndex)

    const showHit = useCallback(
        (hit: SankeyHit, cursor: { x: number; y: number }) => {
            setHover(hitToHoverIndex(layoutRef.current, hit), cursor)
            if (showTooltip) {
                const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
                setTooltipCtx(buildTooltipCtx(layoutRef.current, hit, cursor, canvasBounds))
            }
        },
        [layoutRef, showTooltip, setHover, setTooltipCtx, canvasRef]
    )

    const onMouseMove = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            const current = layoutRef.current
            if (current.nodes.length === 0) {
                return
            }
            const rect = e.currentTarget.getBoundingClientRect()
            const cursor = { x: e.clientX - rect.left, y: e.clientY - rect.top }
            const hit = sankeyHitAt(current, cursor)
            if (!hit) {
                clearTooltip()
                return
            }
            showHit(hit, cursor)
        },
        [layoutRef, showHit, clearTooltip]
    )

    const onMouseLeave = useCallback(() => {
        clearTooltip()
    }, [clearTooltip])

    // Touch devices fire no mousemove before a tap, so the click has to resolve what was tapped
    // itself. As on the cartesian charts, the first tap on a node or ribbon shows its tooltip and
    // only a tap on the element already showing one fires the click handler. Both refs are read
    // at pointerdown because a tap's compatibility mouse events arrive after pointerup.
    const lastPointerTypeRef = useRef<string>('mouse')
    const tapDownHoverIndexRef = useRef<number>(-1)

    const onPointerDown = useCallback(
        (e: React.PointerEvent<HTMLDivElement>) => {
            lastPointerTypeRef.current = e.pointerType
            tapDownHoverIndexRef.current = hoverIndexRef.current
        },
        [hoverIndexRef]
    )

    const onClick = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            const current = layoutRef.current
            let hit = hoverIndexToHit(current, hoverIndexRef.current)
            if (lastPointerTypeRef.current === 'touch') {
                const rect = e.currentTarget.getBoundingClientRect()
                const cursor = { x: e.clientX - rect.left, y: e.clientY - rect.top }
                hit = sankeyHitAt(current, cursor)
                if (!hit) {
                    clearTooltip()
                    return
                }
                if (hitToHoverIndex(current, hit) !== tapDownHoverIndexRef.current) {
                    showHit(hit, cursor)
                    return
                }
            }
            if (!hit) {
                return
            }
            const resolved = resolveHit(current, hit)
            if (resolved.kind === 'node') {
                onNodeClick?.(resolved.node)
            } else {
                onLinkClick?.(resolved.link)
            }
        },
        [layoutRef, hoverIndexRef, clearTooltip, showHit, onNodeClick, onLinkClick]
    )

    const handlers = useMemo(
        () => ({ onMouseMove, onMouseLeave, onClick, onPointerDown }),
        [onMouseMove, onMouseLeave, onClick, onPointerDown]
    )

    // The lifecycle stores the base context; every value it holds was built by `buildTooltipCtx`,
    // so the extra Sankey fields are present.
    return { hoverIndex, hoverPosition, tooltipCtx: tooltipCtx as Ctx | null, handlers }
}
