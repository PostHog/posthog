import { useLayoutEffect } from 'react'

import type {
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    DragRect,
    DrawHoverResult,
    ResolvedSeries,
} from '../types'
import { clearAndPrepare } from './clearCanvas'
import { useHoverAnimation } from './useHoverAnimation'

interface UseChartDrawOptions {
    /** Context for the static layer (grid, lines, areas, points). Redrawn only when chart inputs change. */
    ctx: CanvasRenderingContext2D | null
    /** Context for the hover overlay (highlight rings). Redrawn on every hoverIndex change. */
    overlayCtx: CanvasRenderingContext2D | null
    dimensions: ChartDimensions | null
    scales: ChartScales | null
    series: ResolvedSeries[]
    labels: string[]
    hoverIndex: number
    hoverPosition: { x: number; y: number } | null
    theme: ChartTheme
    dragRect?: DragRect | null
    drawStatic: (args: ChartDrawArgs) => void
    drawHover: (args: ChartDrawArgs) => DrawHoverResult
    /** Duration (ms) of the hover-overlay fade-in/out. `0` disables. */
    hoverAnimationMs?: number
}

export function useChartDraw({
    ctx,
    overlayCtx,
    dimensions,
    scales,
    series,
    labels,
    hoverIndex,
    hoverPosition,
    theme,
    dragRect = null,
    drawStatic,
    drawHover,
    hoverAnimationMs = 0,
}: UseChartDrawOptions): void {
    // Draws synchronously in a layout effect, in the same commit as a `dimensions` change,
    // instead of deferring to a `requestAnimationFrame`. `ResizeObserver` fires and
    // `syncCanvasSize` wipes the backing store before the browser paints the current frame,
    // so a RAF-deferred repaint always lands one frame after that wipe. A container that keeps
    // reporting resizes (see `syncCanvasSize`'s doc comment) therefore never gets a frame where
    // the repaint has caught up, and the chart reads as persistently blank for as long as the
    // resizing continues. Drawing synchronously here means the repaint lands in the same frame
    // as the wipe, so there is no frame where the wipe is visible without it.
    //
    // hoverIndex is deliberately not a dep — a hover sweep shouldn't repaint the static layer.
    useLayoutEffect(() => {
        if (!ctx || !dimensions || !scales || theme.skipDraw) {
            return
        }
        clearAndPrepare(ctx, dimensions)
        try {
            drawStatic({
                ctx,
                dimensions,
                scales,
                series,
                labels,
                hoverIndex: -1,
                hoverPosition: null,
                theme,
                hoverProgress: 1,
                resetHoverFade: () => 1,
            })
        } finally {
            ctx.restore()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ctx, dimensions, scales, series, labels, theme, drawStatic])

    useHoverAnimation({
        overlayCtx,
        dimensions,
        scales,
        series,
        labels,
        hoverIndex,
        hoverPosition,
        theme,
        dragRect,
        drawHover,
        hoverAnimationMs,
    })
}
