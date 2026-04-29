import { useEffect } from 'react'

import type { ChartDimensions, ChartDrawArgs, ChartScales, ChartTheme, Series } from '../types'

interface UseChartDrawOptions {
    /** Context for the static layer (grid, lines, areas, points). Redrawn only when chart inputs change. */
    ctx: CanvasRenderingContext2D | null
    /** Context for the hover overlay (highlight rings). Redrawn on every hoverIndex change. */
    overlayCtx: CanvasRenderingContext2D | null
    dimensions: ChartDimensions | null
    scales: ChartScales | null
    series: Series[]
    labels: string[]
    hoverIndex: number
    theme: ChartTheme
    drawStatic: (args: ChartDrawArgs) => void
    drawHover: (args: ChartDrawArgs) => void
}

function clearAndPrepare(ctx: CanvasRenderingContext2D, dimensions: ChartDimensions): void {
    const dpr = window.devicePixelRatio || 1
    ctx.save()
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, dimensions.width, dimensions.height)
}

export function useChartDraw({
    ctx,
    overlayCtx,
    dimensions,
    scales,
    series,
    labels,
    hoverIndex,
    theme,
    drawStatic,
    drawHover,
}: UseChartDrawOptions): void {
    // Static layer — redraws only when chart inputs change. Excluded `hoverIndex` from deps
    // on purpose so a hover sweep doesn't repaint every line/area/point per move.
    useEffect(() => {
        if (!ctx || !dimensions || !scales) {
            return
        }
        const id = requestAnimationFrame(() => {
            clearAndPrepare(ctx, dimensions)
            drawStatic({ ctx, dimensions, scales, series, labels, hoverIndex: -1, theme })
            ctx.restore()
        })
        return () => cancelAnimationFrame(id)
        // hoverIndex deliberately omitted — see comment above.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ctx, dimensions, scales, series, labels, theme, drawStatic])

    // Hover overlay — redraws only when hoverIndex changes (or chart inputs do). Cheap path:
    // clears the overlay canvas and draws a few highlight rings per series, nothing else.
    useEffect(() => {
        if (!overlayCtx || !dimensions || !scales) {
            return
        }
        const id = requestAnimationFrame(() => {
            clearAndPrepare(overlayCtx, dimensions)
            drawHover({ ctx: overlayCtx, dimensions, scales, series, labels, hoverIndex, theme })
            overlayCtx.restore()
        })
        return () => cancelAnimationFrame(id)
    }, [overlayCtx, dimensions, scales, series, labels, hoverIndex, theme, drawHover])
}
