import React, { useCallback, useMemo } from 'react'

import { originatesInInteractiveOverlay } from '../dom-events'
import { sliceAt } from '../radial-layout'
import type { PieLayout, PieSlice } from '../radial-layout'
import type { ResolvedSeries, TooltipContext } from '../types'
import { useLatest } from './useLatest'
import { useTapTracking } from './useTapTracking'
import { useTooltipLifecycle } from './useTooltipLifecycle'

export interface RadialSlicePayload<Meta = unknown> {
    sliceIndex: number
    series: ResolvedSeries<Meta>
    value: number
    fraction: number
}

interface UseRadialInteractionOptions<Meta> {
    layout: PieLayout<Meta> | null
    canvasRef: React.RefObject<HTMLCanvasElement>
    wrapperRef: React.RefObject<HTMLDivElement>
    showTooltip: boolean
    onSliceClick?: (payload: RadialSlicePayload<Meta>) => void
    /** Allowance beyond `outerRadius` for hit-testing so the grown slice still hovers.
     *  Typically equal to `hoverGrowth`. */
    hitOuterSlack?: number
}

interface UseRadialInteractionResult<Meta> {
    hoverIndex: number
    hoverPosition: { x: number; y: number } | null
    tooltipCtx: TooltipContext<Meta> | null
    handlers: {
        onMouseMove: (e: React.MouseEvent<HTMLDivElement>) => void
        onMouseLeave: () => void
        onClick: (e: React.MouseEvent<HTMLDivElement>) => void
        onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void
    }
}

function buildPieTooltipCtx<Meta>(
    slice: PieSlice<Meta>,
    layout: PieLayout<Meta>,
    cursor: { x: number; y: number } | null,
    canvasBounds: DOMRect
): TooltipContext<Meta> {
    // Centroid of the slice (mid-radius along bisector). The tooltip follows the cursor via
    // `hoverPosition`; this is the fallback anchor for rebuilds with no cursor (e.g. a pin).
    const midR = (layout.innerRadius + layout.outerRadius) / 2
    const ax = layout.cx + Math.sin(slice.centroidAngle) * midR
    const ay = layout.cy - Math.cos(slice.centroidAngle) * midR
    return {
        // Slot the slice index into `dataIndex` so generic overlays / equivalence checks still work.
        dataIndex: slice.seriesIndex,
        label: slice.series.label,
        seriesData: [{ series: slice.series, value: slice.value, color: slice.color, fraction: slice.fraction }],
        position: { x: ax, y: ay },
        hoverPosition: cursor,
        canvasBounds,
        isPinned: false,
    }
}

export function useRadialInteraction<Meta = unknown>({
    layout,
    canvasRef,
    wrapperRef,
    showTooltip,
    onSliceClick,
    hitOuterSlack = 0,
}: UseRadialInteractionOptions<Meta>): UseRadialInteractionResult<Meta> {
    // The pin tracks a *series key* across rebuilds (rather than slice index) so reordering or
    // hiding adjacent slices doesn't silently move the pin to a different slice.
    const layoutRef = useLatest(layout)

    const rebuildPinnedCtx = useCallback(
        (prev: TooltipContext<Meta>): TooltipContext<Meta> | null => {
            const lo = layoutRef.current
            if (!lo) {
                return prev
            }
            const prevKey = prev.seriesData[0]?.series.key
            const slice = lo.slices.find((s) => s.series.key === prevKey)
            if (!slice) {
                return null
            }
            const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
            return buildPieTooltipCtx(slice, lo, prev.hoverPosition, canvasBounds)
        },
        [layoutRef, canvasRef]
    )

    const { hoverIndex, hoverPosition, tooltipCtx, setHover, setTooltipCtx, isPinned, clearTooltip } =
        useTooltipLifecycle<Meta>({
            wrapperRef,
            rebuildPinnedCtx,
            rebuildDeps: [layout],
        })

    const hoverIndexRef = useLatest(hoverIndex)

    const showSlice = useCallback(
        (idx: number, cursor: { x: number; y: number }) => {
            setHover(idx, cursor)
            const lo = layoutRef.current
            if (showTooltip && lo) {
                const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
                setTooltipCtx(buildPieTooltipCtx(lo.slices[idx], lo, cursor, canvasBounds))
            }
        },
        [layoutRef, showTooltip, setHover, setTooltipCtx, canvasRef]
    )

    const onMouseMove = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (isPinned) {
                return
            }
            const lo = layoutRef.current
            if (!lo || lo.slices.length === 0) {
                return
            }
            if (originatesInInteractiveOverlay(e)) {
                clearTooltip()
                return
            }
            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            const cursor = { x: e.clientX - rect.left, y: e.clientY - rect.top }
            const idx = sliceAt(lo, cursor, { outerSlack: hitOuterSlack })
            if (idx < 0) {
                clearTooltip()
                return
            }
            showSlice(idx, cursor)
        },
        [isPinned, layoutRef, hitOuterSlack, showSlice, clearTooltip]
    )

    const onMouseLeave = useCallback(() => {
        if (isPinned) {
            return
        }
        clearTooltip()
    }, [isPinned, clearTooltip])

    // As on the cartesian charts, the first tap on a slice shows its tooltip and only a tap on
    // the slice already showing one fires the click handler.
    const { lastPointerTypeRef, tapDownTooltipIndexRef, onPointerDown } = useTapTracking(tooltipCtx)

    const onClick = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            const isTouch = lastPointerTypeRef.current === 'touch'
            // A click or tap meant for an overlay control must not act on the slice behind it.
            if (originatesInInteractiveOverlay(e)) {
                if (isTouch) {
                    clearTooltip()
                }
                return
            }
            const lo = layoutRef.current
            if (!lo) {
                return
            }
            let idx = hoverIndexRef.current
            if (isTouch) {
                const rect = e.currentTarget.getBoundingClientRect()
                const cursor = { x: e.clientX - rect.left, y: e.clientY - rect.top }
                idx = sliceAt(lo, cursor, { outerSlack: hitOuterSlack })
                if (idx < 0) {
                    clearTooltip()
                    return
                }
                // The tooltip's `dataIndex` is the slice's series index, not its slice index.
                if (lo.slices[idx].seriesIndex !== tapDownTooltipIndexRef.current) {
                    showSlice(idx, cursor)
                    if (showTooltip) {
                        return
                    }
                }
            }
            const slice = lo.slices[idx]
            if (!slice || !onSliceClick) {
                return
            }
            onSliceClick({
                sliceIndex: idx,
                series: slice.series,
                value: slice.value,
                fraction: slice.fraction,
            })
        },
        [
            lastPointerTypeRef,
            tapDownTooltipIndexRef,
            layoutRef,
            hoverIndexRef,
            hitOuterSlack,
            showSlice,
            showTooltip,
            clearTooltip,
            onSliceClick,
        ]
    )

    const handlers = useMemo(
        () => ({ onMouseMove, onMouseLeave, onClick, onPointerDown }),
        [onMouseMove, onMouseLeave, onClick, onPointerDown]
    )

    return { hoverIndex, hoverPosition, tooltipCtx, handlers }
}
