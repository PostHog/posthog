import { useEffect, useRef } from 'react'

import type {
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    OnChartPerformance,
    ResolvedSeries,
} from '../types'
import { useLatest } from './useLatest'

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
    theme: ChartTheme
    drawStatic: (args: ChartDrawArgs) => void
    drawHover: (args: ChartDrawArgs) => void
    /** Optional perf callback fired after each static paint. */
    onPerformance?: OnChartPerformance
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
    onPerformance,
}: UseChartDrawOptions): void {
    // Track the in-flight RAF id in a ref so each new effect run can cancel the previous
    // RAF before scheduling its own. Relying on the React cleanup ordering alone leaves
    // a window where a stale RAF from render N-1 can paint after render N's setup runs.
    const staticRafRef = useRef<number | null>(null)
    const hoverRafRef = useRef<number | null>(null)

    // Captured at the first render of this hook. `useRef`'s initializer runs every render but
    // only the first value is retained, so this approximates the chart's mount time well enough
    // for `sinceMountMs` to be meaningful for the first-paint metric.
    const mountTimeRef = useRef(typeof performance !== 'undefined' ? performance.now() : 0)
    const firstPaintFiredRef = useRef(false)
    // Stash the latest perf callback so changing identity doesn't re-run the static-draw effect.
    const onPerformanceRef = useLatest(onPerformance)

    // Static layer — redraws only when chart inputs change. Excluded `hoverIndex` from deps
    // on purpose so a hover sweep doesn't repaint every line/area/point per move.
    useEffect(() => {
        if (staticRafRef.current != null) {
            cancelAnimationFrame(staticRafRef.current)
            staticRafRef.current = null
        }
        if (!ctx || !dimensions || !scales) {
            return
        }
        staticRafRef.current = requestAnimationFrame(() => {
            staticRafRef.current = null
            clearAndPrepare(ctx, dimensions)
            const drawStart = typeof performance !== 'undefined' ? performance.now() : 0
            drawStatic({ ctx, dimensions, scales, series, labels, hoverIndex: -1, theme })
            const drawEnd = typeof performance !== 'undefined' ? performance.now() : 0
            ctx.restore()
            const onPerf = onPerformanceRef.current
            if (onPerf) {
                const phase = firstPaintFiredRef.current ? 'redraw' : 'first-paint'
                firstPaintFiredRef.current = true
                let dataPointCount = 0
                for (const s of series) {
                    dataPointCount += s.data.length
                }
                onPerf({
                    phase,
                    drawMs: drawEnd - drawStart,
                    sinceMountMs: drawEnd - mountTimeRef.current,
                    seriesCount: series.length,
                    dataPointCount,
                })
            }
        })
        return () => {
            if (staticRafRef.current != null) {
                cancelAnimationFrame(staticRafRef.current)
                staticRafRef.current = null
            }
        }
        // hoverIndex deliberately omitted — see comment above.
        // onPerformanceRef and mountTimeRef are refs and stable.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ctx, dimensions, scales, series, labels, theme, drawStatic])

    // Hover overlay — redraws only when hoverIndex changes (or chart inputs do). Cheap path:
    // clears the overlay canvas and draws a few highlight rings per series, nothing else.
    useEffect(() => {
        if (hoverRafRef.current != null) {
            cancelAnimationFrame(hoverRafRef.current)
            hoverRafRef.current = null
        }
        if (!overlayCtx || !dimensions || !scales) {
            return
        }
        hoverRafRef.current = requestAnimationFrame(() => {
            hoverRafRef.current = null
            clearAndPrepare(overlayCtx, dimensions)
            drawHover({ ctx: overlayCtx, dimensions, scales, series, labels, hoverIndex, theme })
            overlayCtx.restore()
        })
        return () => {
            if (hoverRafRef.current != null) {
                cancelAnimationFrame(hoverRafRef.current)
                hoverRafRef.current = null
            }
        }
    }, [overlayCtx, dimensions, scales, series, labels, hoverIndex, theme, drawHover])
}
