import { useEffect } from 'react'

import type { ChartDimensions, ChartDrawArgs, ChartScales, ChartTheme, Series } from '../types'

interface UseChartDrawOptions {
    ctx: CanvasRenderingContext2D | null
    dimensions: ChartDimensions | null
    scales: ChartScales | null
    series: Series[]
    labels: string[]
    hoverIndex: number
    theme: ChartTheme
    draw: (args: ChartDrawArgs) => void
}

export function useChartDraw({
    ctx,
    dimensions,
    scales,
    series,
    labels,
    hoverIndex,
    theme,
    draw,
}: UseChartDrawOptions): void {
    useEffect(() => {
        if (!ctx || !dimensions || !scales) {
            return
        }

        const id = requestAnimationFrame(() => {
            const dpr = window.devicePixelRatio || 1
            ctx.save()
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
            ctx.clearRect(0, 0, dimensions.width, dimensions.height)

            draw({
                ctx,
                dimensions,
                scales,
                series,
                labels,
                hoverIndex,
                theme,
            })

            ctx.restore()
        })

        return () => cancelAnimationFrame(id)
    }, [ctx, dimensions, scales, series, labels, theme, hoverIndex, draw])
}
