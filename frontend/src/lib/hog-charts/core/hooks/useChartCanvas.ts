import { useEffect, useRef, useState } from 'react'

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

    // Attach the ResizeObserver once. updateSize reads margins from the ref; when margins
    // change, the secondary effect below recomputes dimensions from the cached rect.
    useEffect(() => {
        const wrapper = wrapperRef.current
        if (!wrapper) {
            return
        }

        const updateSize = (): void => {
            const canvas = canvasRef.current
            const overlayCanvas = overlayCanvasRef.current
            if (!canvas || !overlayCanvas) {
                return
            }

            const rect = wrapper.getBoundingClientRect()
            rectRef.current = rect
            const dpr = window.devicePixelRatio || 1

            sizeCanvas(canvas, rect, dpr)
            sizeCanvas(overlayCanvas, rect, dpr)

            const context = canvas.getContext('2d')
            const overlayContext = overlayCanvas.getContext('2d')
            if (!context || !overlayContext) {
                return
            }

            setCanvasState({
                ctx: context,
                overlayCtx: overlayContext,
                dimensions: buildDimensions(rect, marginsRef.current),
            })
        }

        updateSize()

        const observer = new ResizeObserver(() => {
            updateSize()
        })
        observer.observe(wrapper)

        return () => {
            observer.disconnect()
        }
    }, [])

    // When margins change without a resize, recompute dimensions from the cached rect.
    useEffect(() => {
        const rect = rectRef.current
        if (!rect) {
            return
        }
        setCanvasState((prev) => (prev ? { ...prev, dimensions: buildDimensions(rect, margins) } : prev))
    }, [margins.left, margins.right, margins.top, margins.bottom])

    return {
        canvasRef,
        overlayCanvasRef,
        wrapperRef,
        dimensions: canvasState?.dimensions ?? null,
        ctx: canvasState?.ctx ?? null,
        overlayCtx: canvasState?.overlayCtx ?? null,
    }
}
