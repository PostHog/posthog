import React, { useCallback, useMemo } from 'react'

import { sliceAt } from '../radial-layout'
import type { PieLayout, PieSlice } from '../radial-layout'
import type { ResolvedSeries, TooltipContext } from '../types'
import { useLatest } from './useLatest'
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
        onClick: () => void
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

    const onMouseMove = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (isPinned) {
                return
            }
            const lo = layoutRef.current
            if (!lo || lo.slices.length === 0) {
                return
            }
            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const mouseY = e.clientY - rect.top
            const cursor = { x: mouseX, y: mouseY }
            const idx = sliceAt(lo, cursor, { outerSlack: hitOuterSlack })
            if (idx < 0) {
                clearTooltip()
                return
            }
            setHover(idx, cursor)
            if (showTooltip) {
                const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
                setTooltipCtx(buildPieTooltipCtx(lo.slices[idx], lo, cursor, canvasBounds))
            }
        },
        [isPinned, layoutRef, hitOuterSlack, showTooltip, setHover, setTooltipCtx, clearTooltip, canvasRef]
    )

    const onMouseLeave = useCallback(() => {
        if (isPinned) {
            return
        }
        clearTooltip()
    }, [isPinned, clearTooltip])

    const onClick = useCallback(() => {
        const idx = hoverIndexRef.current
        if (idx < 0 || !onSliceClick) {
            return
        }
        const lo = layoutRef.current
        if (!lo) {
            return
        }
        const slice = lo.slices[idx]
        if (!slice) {
            return
        }
        onSliceClick({
            sliceIndex: idx,
            series: slice.series,
            value: slice.value,
            fraction: slice.fraction,
        })
    }, [hoverIndexRef, layoutRef, onSliceClick])

    const handlers = useMemo(() => ({ onMouseMove, onMouseLeave, onClick }), [onMouseMove, onMouseLeave, onClick])

    return { hoverIndex, hoverPosition, tooltipCtx, handlers }
}
