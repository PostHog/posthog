import { useCallback, useEffect, useRef, useState } from 'react'

import type { ChartDimensions, ChartMargins } from '../types'
import { useLatest } from './useLatest'

interface UseChartCanvasOptions {
    margins: ChartMargins
}

// Some layouts settle a few frames after mount rather than at mount — e.g. a chart with a
// `stepFooter` reports its band positions after the first paint, then renders a footer that
// shrinks the plot. That resize is delivered by the ResizeObserver, but under a heavy commit
// (an insight swapping from a blocking state back to the chart) the notification can be
// coalesced or dropped, leaving the chart painted at a stale size with no trigger to repaint.
// Re-measuring across the first frames after mount converges the chart to its settled size
// independently of whether that one notification arrives.
const RESIZE_SETTLE_FRAMES = 8

interface CanvasState {
    dimensions: ChartDimensions
    ctx: CanvasRenderingContext2D
    overlayCtx: CanvasRenderingContext2D
}

interface UseChartCanvasResult {
    canvasRef: React.RefObject<HTMLCanvasElement>
    overlayCanvasRef: React.RefObject<HTMLCanvasElement>
    wrapperRef: React.RefObject<HTMLDivElement>
    dimensions: ChartDimensions | null
    ctx: CanvasRenderingContext2D | null
    overlayCtx: CanvasRenderingContext2D | null
}

function sizeCanvas(canvas: HTMLCanvasElement, rect: DOMRect, dpr: number): void {
    canvas.width = rect.width * dpr
    canvas.height = rect.height * dpr
    canvas.style.width = `${rect.width}px`
    canvas.style.height = `${rect.height}px`
}

function buildDimensions(rect: DOMRect, margins: ChartMargins): ChartDimensions {
    return {
        width: rect.width,
        height: rect.height,
        plotLeft: margins.left,
        plotTop: margins.top,
        plotWidth: Math.max(0, rect.width - margins.left - margins.right),
        plotHeight: Math.max(0, rect.height - margins.top - margins.bottom),
    }
}

export function useChartCanvas(options: UseChartCanvasOptions): UseChartCanvasResult {
    const { margins } = options
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const overlayCanvasRef = useRef<HTMLCanvasElement | null>(null)
    const wrapperRef = useRef<HTMLDivElement | null>(null)
    const [canvasState, setCanvasState] = useState<CanvasState | null>(null)

    // Keep margins behind a ref so the ResizeObserver effect can read the latest values
    // without re-binding when only margins change — re-binding risks a feedback loop with
    // y-tick-width measurement.
    const marginsRef = useLatest(margins)
    const rectRef = useRef<DOMRect | null>(null)

    // Measure the wrapper and resize + commit the canvas. Returns true only when it committed
    // a new size, so callers that poll (the settle loop below) can detect convergence.
    const applySize = useCallback((): boolean => {
        const wrapper = wrapperRef.current
        const canvas = canvasRef.current
        const overlayCanvas = overlayCanvasRef.current
        if (!wrapper || !canvas || !overlayCanvas) {
            return false
        }

        const rect = wrapper.getBoundingClientRect()

        // A zero-area rect means the wrapper isn't laid out yet (still inside a collapsing or
        // blocking state). Committing it would size the canvas to 0×0 and paint a blank chart
        // that never recovers if no later resize notification arrives — wait for a real rect.
        if (rect.width === 0 || rect.height === 0) {
            return false
        }

        // Skip redundant work when the size hasn't changed. Resizing the canvas clears its
        // bitmap, so an unconditional re-run on every notification would flash the chart blank;
        // margins-only changes are handled by the secondary effect below without a resize.
        const prev = rectRef.current
        if (prev && prev.width === rect.width && prev.height === rect.height) {
            return false
        }

        rectRef.current = rect
        const dpr = window.devicePixelRatio || 1

        sizeCanvas(canvas, rect, dpr)
        sizeCanvas(overlayCanvas, rect, dpr)

        const context = canvas.getContext('2d')
        const overlayContext = overlayCanvas.getContext('2d')
        if (!context || !overlayContext) {
            return false
        }

        setCanvasState({
            ctx: context,
            overlayCtx: overlayContext,
            dimensions: buildDimensions(rect, marginsRef.current),
        })
        return true
    }, [marginsRef])

    // Attach the ResizeObserver once. `applySize` reads margins from a ref, so it stays stable
    // and the observer is never re-bound; when only margins change, the secondary effect below
    // recomputes dimensions from the cached rect instead.
    useEffect(() => {
        const wrapper = wrapperRef.current
        if (!wrapper) {
            return
        }

        applySize()

        const observer = new ResizeObserver(() => {
            applySize()
        })
        observer.observe(wrapper)

        return () => {
            observer.disconnect()
        }
    }, [applySize])

    // Re-measure across the first frames after mount so a layout that settles late (see
    // RESIZE_SETTLE_FRAMES) always converges, even if its single ResizeObserver notification is
    // dropped. `applySize` no-ops once the size is stable, so this is a bounded, cheap safety net.
    useEffect(() => {
        let framesLeft = RESIZE_SETTLE_FRAMES
        let raf = 0
        const tick = (): void => {
            applySize()
            if (--framesLeft > 0) {
                raf = requestAnimationFrame(tick)
            }
        }
        raf = requestAnimationFrame(tick)
        return () => cancelAnimationFrame(raf)
    }, [applySize])

    // When margins change without a resize, recompute dimensions from the cached rect.
    useEffect(() => {
        const rect = rectRef.current
        if (!rect) {
            return
        }
        setCanvasState((prev) => (prev ? { ...prev, dimensions: buildDimensions(rect, margins) } : prev))
    }, [margins.left, margins.right, margins.top, margins.bottom, margins])

    return {
        canvasRef,
        overlayCanvasRef,
        wrapperRef,
        dimensions: canvasState?.dimensions ?? null,
        ctx: canvasState?.ctx ?? null,
        overlayCtx: canvasState?.overlayCtx ?? null,
    }
}
