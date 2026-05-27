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
    /** Duration (ms) of the fade-in animation on the hover overlay when the hovered data
     *  point changes. `0` disables. The animation is owned by the RAF loop here — not by
     *  React state — so it's robust against rapid mousemove events. */
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
    // Track the in-flight RAF id in a ref so each new effect run can cancel the previous
    // RAF before scheduling its own. Relying on the React cleanup ordering alone leaves
    // a window where a stale RAF from render N-1 can paint after render N's setup runs.
    const staticRafRef = useRef<number | null>(null)
    const hoverRafRef = useRef<number | null>(null)
    // Hover-fade animation state lives in a ref so the RAF loop can read/write it without
    // dragging React's render cycle into the per-frame path.
    const hoverAnimRef = useRef<{ idx: number; startTime: number }>({ idx: -1, startTime: 0 })
    // Tracks whether the previous frame drew a visible highlight. Used to freeze the fade
    // timer while invisible (cursor in a band gap, etc.) so the animation always starts at
    // progress 0 the moment something visible appears under the cursor.
    const drewVisibleRef = useRef(false)
    // Mirror inputs that change on every mousemove into refs so the hover effect only
    // re-arms its RAF on changes that actually require it (canvas / dimensions / scales /
    // hoverIndex / animation duration). Without this, `hoverPosition` — a fresh `{x,y}` per
    // mousemove — tears down and reschedules the RAF on every pixel of mouse motion.
    const drawHoverRef = useLatest(drawHover)
    const hoverPositionRef = useLatest(hoverPosition)
    const seriesRef = useLatest(series)
    const labelsRef = useLatest(labels)
    const themeRef = useLatest(theme)

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
        // hoverIndex deliberately omitted — see comment above.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ctx, dimensions, scales, series, labels, theme, drawStatic])

    // Hover overlay — when `hoverAnimationMs > 0` and the hovered index just changed, the
    // RAF loop ticks every frame until `hoverProgress` reaches 1. Once it does, the loop
    // exits and we only redraw on the next dep change. The animation is timer-driven from
    // a ref so cancelled-and-restarted RAFs resume the fade seamlessly.
    useEffect(() => {
        if (hoverRafRef.current != null) {
            cancelAnimationFrame(hoverRafRef.current)
            hoverRafRef.current = null
        }
        if (!overlayCtx || !dimensions || !scales) {
            return
        }
        // Reset the fade timer when the hovered index changes. Also force-invalidate the
        // visibility flag so the next visible frame restarts the fade at progress 0 even if
        // the previous bar's highlight was still visible.
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
            // If last frame drew nothing visible, the animation hasn't really "started" yet —
            // push startTime forward so progress stays at 0 until something visible appears.
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
            // Recompute progress in case the chart type called resetHoverFade mid-draw — the
            // local `hoverProgress` above could have been 1 (animation thought complete) but
            // the chart type just restarted it, so we need to keep the loop alive.
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
        // series / labels / theme / hoverPosition / drawHover are read from refs above so
        // mousemove and re-memoization don't tear down the RAF loop on every change.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [overlayCtx, dimensions, scales, hoverIndex, hoverAnimationMs])
}
