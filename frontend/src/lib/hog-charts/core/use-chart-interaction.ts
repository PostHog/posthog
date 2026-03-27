import React, { useCallback, useState } from 'react'

import { buildPointClickData, buildTooltipContext, findNearestIndex, isInPlotArea } from './interaction'
import type { ChartDimensions, ChartScales, PointClickData, Series, TooltipContext } from './types'

interface UseChartInteractionOptions {
    scales: ChartScales | null
    dimensions: ChartDimensions | null
    labels: string[]
    series: Series[]
    canvasRef: React.RefObject<HTMLCanvasElement | null>
    showTooltip: boolean
    onPointClick?: (data: PointClickData) => void
    stackedData?: Map<string, number[]>
}

interface UseChartInteractionResult {
    hoverIndex: number
    tooltipCtx: TooltipContext | null
    handlers: {
        onMouseMove: (e: React.MouseEvent<HTMLDivElement>) => void
        onMouseLeave: () => void
        onClick: () => void
    }
}

export function useChartInteraction({
    scales,
    dimensions,
    labels,
    series,
    canvasRef,
    showTooltip,
    onPointClick,
    stackedData,
}: UseChartInteractionOptions): UseChartInteractionResult {
    const [hoverIndex, setHoverIndex] = useState<number>(-1)
    const [tooltipCtx, setTooltipCtx] = useState<TooltipContext | null>(null)

    const onMouseMove = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!scales || !dimensions) {
                return
            }

            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const mouseY = e.clientY - rect.top

            if (!isInPlotArea(mouseX, mouseY, dimensions)) {
                setHoverIndex(-1)
                setTooltipCtx(null)
                return
            }

            const index = findNearestIndex(mouseX, labels, scales.x)
            setHoverIndex(index)

            if (index >= 0 && showTooltip) {
                const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
                const newTooltipCtx = buildTooltipContext(
                    index,
                    series,
                    labels,
                    scales.x,
                    scales.y,
                    canvasBounds,
                    stackedData
                )
                setTooltipCtx(newTooltipCtx)
            }
        },
        [scales, dimensions, labels, series, showTooltip, stackedData, canvasRef]
    )

    const onMouseLeave = useCallback(() => {
        setHoverIndex(-1)
        setTooltipCtx(null)
    }, [])

    const onClick = useCallback(() => {
        if (onPointClick && hoverIndex >= 0) {
            const clickData = buildPointClickData(hoverIndex, series, labels, stackedData)
            if (clickData) {
                onPointClick(clickData)
            }
        }
    }, [onPointClick, hoverIndex, series, labels, stackedData])

    return {
        hoverIndex,
        tooltipCtx,
        handlers: { onMouseMove, onMouseLeave, onClick },
    }
}
