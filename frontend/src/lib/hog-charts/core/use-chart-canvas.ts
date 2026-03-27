import { useEffect, useRef, useState } from 'react'

import type { ChartDimensions, ChartMargins } from './types'

interface UseChartCanvasOptions {
    margins: ChartMargins
}

interface UseChartCanvasResult {
    canvasRef: React.RefObject<HTMLCanvasElement | null>
    wrapperRef: React.RefObject<HTMLDivElement | null>
    dimensions: ChartDimensions | null
    ctx: CanvasRenderingContext2D | null
}

export function useChartCanvas(options: UseChartCanvasOptions): UseChartCanvasResult {
    const { margins } = options
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const wrapperRef = useRef<HTMLDivElement | null>(null)
    const [dimensions, setDimensions] = useState<ChartDimensions | null>(null)
    const [ctx, setCtx] = useState<CanvasRenderingContext2D | null>(null)

    // Update canvas size and DPR scaling
    const updateSize = (): void => {
        const canvas = canvasRef.current
        const wrapper = wrapperRef.current
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
        if (context) {
            context.scale(dpr, dpr)
            setCtx(context)
        }

        const dims: ChartDimensions = {
            width: rect.width,
            height: rect.height,
            plotLeft: margins.left,
            plotTop: margins.top,
            plotWidth: Math.max(0, rect.width - margins.left - margins.right),
            plotHeight: Math.max(0, rect.height - margins.top - margins.bottom),
        }
        setDimensions(dims)
    }

    // ResizeObserver for responsive sizing
    useEffect(() => {
        const wrapper = wrapperRef.current
        if (!wrapper) {
            return
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

    return { canvasRef, wrapperRef, dimensions, ctx }
}
