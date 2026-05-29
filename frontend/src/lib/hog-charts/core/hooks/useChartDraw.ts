import { useEffect, useRef } from 'react'

import type { ChartDimensions, ChartDrawArgs, ChartScales, ChartTheme, DrawHoverResult, ResolvedSeries } from '../types'
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
    hoverPosition: { x: number; y: number } | null
    theme: ChartTheme
    drawStatic: (args: ChartDrawArgs) => void
    drawHover: (args: ChartDrawArgs) => DrawHoverResult
    /** Duration (ms) of the hover-overlay fade-in. `0` disables. */
    hoverAnimationMs?: number
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
    hoverPosition,
    theme,
    drawStatic,
    drawHover,
    hoverAnimationMs = 0,
}: UseChartDrawOptions): void {
    // Cancel the prior RAF on effect re-run — relying on cleanup ordering alone leaves a
    // window where a stale RAF can paint after the new setup runs.
    const staticRafRef = useRef<number | null>(null)
    const hoverRafRef = useRef<number | null>(null)
    const hoverAnimRef = useRef<{ idx: number; startTime: number }>({ idx: -1, startTime: 0 })
    // Freezes the fade timer while invisible (cursor in a band gap) so the fade always
    // starts at progress 0 when something visible first appears.
    const drewVisibleRef = useRef(false)
    // Mirror everything that changes per-mousemove so the hover effect's dep array stays
    // small — otherwise we'd tear down and re-arm the RAF every mouse pixel.
    const drawHoverRef = useLatest(drawHover)
    const hoverPositionRef = useLatest(hoverPosition)
    const seriesRef = useLatest(series)
    const labelsRef = useLatest(labels)
    const themeRef = useLatest(theme)

    // hoverIndex is deliberately not a dep — a hover sweep shouldn't repaint the static layer.
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

    // The RAF loop ticks until hoverProgress reaches 1, then exits and waits for the next
    // dep change. Timer is held in a ref so cancel/restart cycles resume the fade smoothly.
    useEffect(() => {
        if (hoverRafRef.current != null) {
            cancelAnimationFrame(hoverRafRef.current)
            hoverRafRef.current = null
        }
        if (!overlayCtx || !dimensions || !scales) {
            return
        }
        // Restart the fade on hoverIndex change — invalidate drewVisible too so the next
        // visible frame starts at progress 0, not where the previous bar's fade left off.
        if (hoverIndex !== hoverAnimRef.current.idx) {
            hoverAnimRef.current.idx = hoverIndex
            hoverAnimRef.current.startTime = performance.now()
            drewVisibleRef.current = false
        }
        const resetHoverFade = (): number => {
            hoverAnimRef.current.startTime = performance.now()
            return 0
        }
        const tick = (): void => {
            // Pin progress to 0 while invisible — see drewVisibleRef comment above.
            if (!drewVisibleRef.current) {
                hoverAnimRef.current.startTime = performance.now()
            }
            const elapsed = performance.now() - hoverAnimRef.current.startTime
            const hoverProgress = hoverAnimationMs > 0 ? Math.min(1, elapsed / hoverAnimationMs) : 1
            clearAndPrepare(overlayCtx, dimensions)
            const drewVisible = drawHoverRef.current({
                ctx: overlayCtx,
                dimensions,
                scales,
                series: seriesRef.current,
                labels: labelsRef.current,
                hoverIndex,
                hoverPosition: hoverPositionRef.current,
                theme: themeRef.current,
                hoverProgress,
                resetHoverFade,
            })
            overlayCtx.restore()
            drewVisibleRef.current = drewVisible
            // Recompute after the draw — the chart type may have called resetHoverFade
            // mid-draw, which would leave the cached hoverProgress stale.
            const liveElapsed = performance.now() - hoverAnimRef.current.startTime
            const liveProgress = hoverAnimationMs > 0 ? Math.min(1, liveElapsed / hoverAnimationMs) : 1
            if (drewVisible && liveProgress < 1 && hoverIndex >= 0) {
                hoverRafRef.current = requestAnimationFrame(tick)
            } else {
                hoverRafRef.current = null
            }
        }
        hoverRafRef.current = requestAnimationFrame(tick)
        return () => {
            if (hoverRafRef.current != null) {
                cancelAnimationFrame(hoverRafRef.current)
                hoverRafRef.current = null
            }
        }
        // hoverPosition is in the dep array (not the ref) so the overlay redraws when the
        // cursor moves *within* the same band — bar charts decide on a hit per-frame in
        // `drawHover`, and entering a bar from canvas-empty-space doesn't change hoverIndex.
        // The fade timer only resets on hoverIndex change (see check above), so re-running
        // the effect per mousemove doesn't restart the animation.
        // series/labels/theme/drawHover are read via refs — see top of hook.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [overlayCtx, dimensions, scales, hoverIndex, hoverPosition, hoverAnimationMs])
}
