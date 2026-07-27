import { useEffect, useRef } from 'react'

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
    // Cancel the prior RAF on effect re-run — relying on cleanup ordering alone leaves a
    // window where a stale RAF can paint after the new setup runs.
    const staticRafRef = useRef<number | null>(null)

    // hoverIndex is deliberately not a dep — a hover sweep shouldn't repaint the static layer.
    useEffect(() => {
        if (staticRafRef.current != null) {
            cancelAnimationFrame(staticRafRef.current)
            staticRafRef.current = null
        }
        if (!ctx || !dimensions || !scales || theme.skipDraw) {
            return
        }
        staticRafRef.current = requestAnimationFrame(() => {
            staticRafRef.current = null
            clearAndPrepare(ctx, dimensions)
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
            ctx.restore()
        })
        return () => {
            if (staticRafRef.current != null) {
                cancelAnimationFrame(staticRafRef.current)
                staticRafRef.current = null
            }
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
