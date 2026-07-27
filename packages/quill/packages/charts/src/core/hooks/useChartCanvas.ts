import { useEffect, useRef, useState } from 'react'

import { buildDimensions, sameDimensions, syncCanvasSize, type SizeRect } from '../canvas-size'
import type { ChartDimensions, ChartMargins } from '../types'
import { useLatest } from './useLatest'

interface UseChartCanvasOptions {
    margins: ChartMargins
}

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
    const rectRef = useRef<SizeRect | null>(null)

    // Attach the ResizeObserver once. updateSize reads margins from the ref; when margins
    // change, the secondary effect below recomputes dimensions from the cached rect.
    useEffect(() => {
        const wrapper = wrapperRef.current
        if (!wrapper) {
            return
        }

        // `forceRepaint` publishes fresh state even when nothing moved — for a restored context,
        // whose bitmap came back blank while every value stayed identical.
        const updateSize = (forceRepaint = false): void => {
            const canvas = canvasRef.current
            const overlayCanvas = overlayCanvasRef.current
            if (!canvas || !overlayCanvas) {
                return
            }

            // Resolve the contexts *before* touching the canvas size. Bailing out afterwards
            // would leave both bitmaps wiped with no state change to schedule a repaint.
            const context = canvas.getContext('2d')
            const overlayContext = overlayCanvas.getContext('2d')
            if (!context || !overlayContext) {
                return
            }

            const rect = wrapper.getBoundingClientRect()
            rectRef.current = rect
            const dpr = window.devicePixelRatio || 1

            const staticWiped = syncCanvasSize(canvas, rect, dpr)
            const overlayWiped = syncCanvasSize(overlayCanvas, rect, dpr)

            // The draw loops key on `dimensions` *identity*, so publishing a fresh object is what
            // schedules a repaint. That matters whenever a bitmap was discarded without any value
            // moving (a device-pixel-ratio change, a restored context): the wipe flags and
            // `forceRepaint` are the only reasons a new object goes out. Reusing `prev.dimensions`
            // when the values match would silently reinstate the blank canvas.
            const next = buildDimensions(rect, marginsRef.current)
            setCanvasState((prev) =>
                prev &&
                !forceRepaint &&
                !staticWiped &&
                !overlayWiped &&
                prev.ctx === context &&
                prev.overlayCtx === overlayContext &&
                sameDimensions(prev.dimensions, next)
                    ? prev
                    : { ctx: context, overlayCtx: overlayContext, dimensions: next }
            )
        }

        updateSize()

        const observer = new ResizeObserver(() => {
            updateSize()
        })
        observer.observe(wrapper)

        // A 2D context can be lost when the browser reclaims canvas memory. Its bitmap comes back
        // blank on `contextrestored` and nothing repaints on its own, so the canvas stays empty
        // while every DOM overlay (axis labels, goal lines, tooltip) keeps rendering against valid
        // dimensions. Not supported everywhere: Firefox 125+ and Chrome 99+ fire it, Safari never
        // does. `contextlost` is deliberately not handled — preventing its default tells the browser
        // we'll restore the context ourselves, and then it never restores.
        const onContextRestored = (): void => updateSize(true)
        const restoreTargets = [canvasRef.current, overlayCanvasRef.current].filter(
            (canvas): canvas is HTMLCanvasElement => !!canvas
        )
        restoreTargets.forEach((canvas) => canvas.addEventListener('contextrestored', onContextRestored))

        return () => {
            observer.disconnect()
            restoreTargets.forEach((canvas) => canvas.removeEventListener('contextrestored', onContextRestored))
        }
        // Bind the observer once. `marginsRef` is a ref so `updateSize` always reads the
        // latest margins; depending on `marginsRef.current` here would disconnect and re-run
        // `updateSize` on every margins change. The effect below handles margins-only updates.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // When margins change without a resize, recompute dimensions from the cached rect.
    useEffect(() => {
        const rect = rectRef.current
        if (!rect) {
            return
        }
        setCanvasState((prev) => {
            if (!prev) {
                return prev
            }
            const next = buildDimensions(rect, margins)
            return sameDimensions(prev.dimensions, next) ? prev : { ...prev, dimensions: next }
        })
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
