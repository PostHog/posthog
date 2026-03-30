import React, { useCallback, useMemo, useRef, useState } from 'react'

import { buildPointClickData, buildTooltipContext, findNearestIndex, isInPlotArea } from '../interaction'
import type { ChartDimensions, ChartScales, PointClickData, ResolveValueFn, Series, TooltipContext } from '../types'

const defaultResolveValue: ResolveValueFn = (series, dataIndex) => series.data[dataIndex] ?? 0

interface UseChartInteractionOptions {
    scales: ChartScales | null
    dimensions: ChartDimensions | null
    labels: string[]
    series: Series[]
    canvasRef: React.RefObject<HTMLCanvasElement>
    showTooltip: boolean
    onPointClick?: (data: PointClickData) => void
    resolveValue?: ResolveValueFn
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
    resolveValue = defaultResolveValue,
}: UseChartInteractionOptions): UseChartInteractionResult {
    const [hoverIndex, setHoverIndex] = useState<number>(-1)
    const [tooltipCtx, setTooltipCtx] = useState<TooltipContext | null>(null)
    const hoverIndexRef = useRef(hoverIndex)
    hoverIndexRef.current = hoverIndex

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
                    resolveValue
                )
                setTooltipCtx(newTooltipCtx)
            }
        },
        [scales, dimensions, labels, series, showTooltip, resolveValue, canvasRef]
    )

    const onMouseLeave = useCallback(() => {
        setHoverIndex(-1)
        setTooltipCtx(null)
    }, [])

    const onClick = useCallback(() => {
        if (onPointClick && hoverIndexRef.current >= 0) {
            const clickData = buildPointClickData(hoverIndexRef.current, series, labels, resolveValue)
            if (clickData) {
                onPointClick(clickData)
            }
        }
    }, [onPointClick, series, labels, resolveValue])

    const handlers = useMemo(() => ({ onMouseMove, onMouseLeave, onClick }), [onMouseMove, onMouseLeave, onClick])

    return { hoverIndex, tooltipCtx, handlers }
}
