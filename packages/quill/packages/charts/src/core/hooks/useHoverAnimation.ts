import { useEffect, useRef } from 'react'

import { monotonicNow } from '../time'
import type {
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    DragRect,
    DrawHoverResult,
    ResolvedSeries,
} from '../types'
import { clearAndPrepare, releaseCanvas } from './clearCanvas'

interface UseHoverAnimationOptions {
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
    drawHover: (args: ChartDrawArgs) => DrawHoverResult
    /** Duration (ms) of the hover-overlay fade-in. `0` snaps instantly. */
    hoverAnimationMs: number
}

/**
 * Drives the hover overlay's fade-in on its own RAF loop. The highlight eases in (progress 0→1)
 * when the cursor enters a band and cross-fades when it moves between bands. The overlay clears
 * when the cursor leaves (hoverIndex < 0).
 */
export function useHoverAnimation({
    overlayCtx,
    dimensions,
    scales,
    series,
    labels,
    hoverIndex,
    hoverPosition,
    theme,
    dragRect = null,
    drawHover,
    hoverAnimationMs,
}: UseHoverAnimationOptions): void {
    const fade = useRef({ index: -1, startTime: 0, visible: false })

    // Bar charts hit-test per frame, so a move within one band must redraw.
    useEffect(() => {
        if (!overlayCtx || !dimensions || !scales || theme.skipDraw) {
            return
        }
        const state = fade.current
        if (hoverIndex !== state.index) {
            state.index = hoverIndex
            state.startTime = monotonicNow()
            state.visible = false
        }
        const progress = (): number =>
            hoverAnimationMs > 0 ? Math.min(1, (monotonicNow() - state.startTime) / hoverAnimationMs) : 1
        const resetHoverFade = (): number => {
            state.startTime = monotonicNow()
            return 0
        }
        let raf: number | null = null
        const tick = (): void => {
            raf = null
            if (!state.visible) {
                state.startTime = monotonicNow()
            }
            // Idle (no hover, no drag) draws nothing, so release the bitmap instead of clearing a
            // full-size one. drawHover still runs, against the empty canvas, so chart types can
            // reset their own hover state.
            if (hoverIndex < 0 && !dragRect) {
                releaseCanvas(overlayCtx.canvas)
                overlayCtx.save()
            } else {
                clearAndPrepare(overlayCtx, dimensions)
            }
            try {
                state.visible = drawHover({
                    ctx: overlayCtx,
                    dimensions,
                    scales,
                    series,
                    labels,
                    hoverIndex,
                    hoverPosition,
                    theme,
                    hoverProgress: progress(),
                    resetHoverFade,
                    dragRect,
                })
            } finally {
                overlayCtx.restore()
            }
            if (state.visible && hoverIndex >= 0 && progress() < 1) {
                raf = requestAnimationFrame(tick)
            }
        }
        raf = requestAnimationFrame(tick)
        return () => {
            if (raf != null) {
                cancelAnimationFrame(raf)
            }
        }
    }, [
        overlayCtx,
        dimensions,
        scales,
        series,
        labels,
        theme,
        drawHover,
        hoverIndex,
        hoverPosition,
        dragRect,
        hoverAnimationMs,
    ])
}
