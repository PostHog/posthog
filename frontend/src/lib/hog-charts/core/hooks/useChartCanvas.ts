import { useEffect, useRef, useState } from 'react'

import type { ChartDimensions, ChartMargins } from '../types'

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

    useEffect(() => {
        const wrapper = wrapperRef.current
        if (!wrapper) {
            return
        }

        const sizeCanvas = (canvas: HTMLCanvasElement, rect: DOMRect, dpr: number): void => {
            canvas.width = rect.width * dpr
            canvas.height = rect.height * dpr
            canvas.style.width = `${rect.width}px`
            canvas.style.height = `${rect.height}px`
        }

        const updateSize = (): void => {
            const canvas = canvasRef.current
            const overlayCanvas = overlayCanvasRef.current
            if (!canvas || !overlayCanvas || !wrapper) {
                return
            }

            const rect = wrapper.getBoundingClientRect()
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
                dimensions: {
                    width: rect.width,
                    height: rect.height,
                    plotLeft: margins.left,
                    plotTop: margins.top,
                    plotWidth: Math.max(0, rect.width - margins.left - margins.right),
                    plotHeight: Math.max(0, rect.height - margins.top - margins.bottom),
                },
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
