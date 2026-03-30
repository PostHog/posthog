import { useEffect, useRef, useState } from 'react'

import type { ChartDimensions, ChartMargins } from '../types'

interface UseChartCanvasOptions {
    margins: ChartMargins
}

interface CanvasState {
    dimensions: ChartDimensions
    ctx: CanvasRenderingContext2D
}

interface UseChartCanvasResult {
    canvasRef: React.RefObject<HTMLCanvasElement>
    wrapperRef: React.RefObject<HTMLDivElement>
    dimensions: ChartDimensions | null
    ctx: CanvasRenderingContext2D | null
}

export function useChartCanvas(options: UseChartCanvasOptions): UseChartCanvasResult {
    const { margins } = options
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const wrapperRef = useRef<HTMLDivElement | null>(null)
    const [canvasState, setCanvasState] = useState<CanvasState | null>(null)

    useEffect(() => {
        const wrapper = wrapperRef.current
        if (!wrapper) {
            return
        }

        const updateSize = (): void => {
            const canvas = canvasRef.current
            if (!canvas || !wrapper) {
                return
            }

            const rect = wrapper.getBoundingClientRect()
            const dpr = window.devicePixelRatio || 1

            canvas.width = rect.width * dpr
            canvas.height = rect.height * dpr
            canvas.style.width = `${rect.width}px`
            canvas.style.height = `${rect.height}px`

            const context = canvas.getContext('2d')
            if (!context) {
                return
            }

            setCanvasState({
                ctx: context,
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
        wrapperRef,
        dimensions: canvasState?.dimensions ?? null,
        ctx: canvasState?.ctx ?? null,
    }
}
