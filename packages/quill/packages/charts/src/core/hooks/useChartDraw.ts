import { useEffect } from 'react'

import { markPaintDone, markPaintPending } from '../paint-state'
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
    series?: ResolvedSeries[]
    labels?: string[]
    hoverIndex: number
    hoverPosition: { x: number; y: number } | null
    theme: ChartTheme
    dragRect?: DragRect | null
    drawStatic: (args: ChartDrawArgs) => void
    drawHover: (args: ChartDrawArgs) => DrawHoverResult
    /** Duration (ms) of the hover-overlay fade-in/out. `0` disables. */
    hoverAnimationMs?: number
}

// Shared defaults: a fresh `[]` per render would repaint the static layer on every hover.
const NO_SERIES: ResolvedSeries[] = []
const NO_LABELS: string[] = []

export function useChartDraw({
    ctx,
    overlayCtx,
    dimensions,
    scales,
    series = NO_SERIES,
    labels = NO_LABELS,
    hoverIndex,
    hoverPosition,
    theme,
    dragRect = null,
    drawStatic,
    drawHover,
    hoverAnimationMs = 0,
}: UseChartDrawOptions): void {
    // hoverIndex is deliberately not a dep — a hover sweep shouldn't repaint the static layer.
    useEffect(() => {
        if (!ctx) {
            return
        }
        // Nothing to paint is a settled state too, or a snapshot runner would wait on it.
        if (!dimensions || !scales || theme.skipDraw) {
            markPaintDone(ctx.canvas)
            return
        }
        markPaintPending(ctx.canvas)
        const raf = requestAnimationFrame(() => {
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
                markPaintDone(ctx.canvas)
            }
        })
        return () => cancelAnimationFrame(raf)
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
