import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { buildPointClickData, buildTooltipContext, findNearestIndex, isInPlotArea } from '../interaction'
import type { ChartDimensions, ChartScales, PointClickData, ResolveValueFn, Series, TooltipContext } from '../types'

const defaultResolveValue: ResolveValueFn = (series, dataIndex) => series.data[dataIndex] ?? 0

interface UseChartInteractionOptions {
    scales: ChartScales | null
    dimensions: ChartDimensions | null
    labels: string[]
    series: Series[]
    canvasRef: React.RefObject<HTMLCanvasElement>
    wrapperRef: React.RefObject<HTMLDivElement>
    showTooltip: boolean
    pinnable: boolean
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
    wrapperRef,
    showTooltip,
    pinnable,
    onPointClick,
    resolveValue = defaultResolveValue,
}: UseChartInteractionOptions): UseChartInteractionResult {
    const [hoverIndex, setHoverIndex] = useState<number>(-1)
    const [tooltipCtx, setTooltipCtx] = useState<TooltipContext | null>(null)
    const hoverIndexRef = useRef<number>(hoverIndex)
    hoverIndexRef.current = hoverIndex

    const clearTooltip = useCallback(() => {
        setHoverIndex(-1)
        setTooltipCtx(null)
    }, [])

    const unpin = useCallback(() => {
        setTooltipCtx((prev) => (prev?.isPinned ? null : prev))
    }, [])

    const isPinned = tooltipCtx?.isPinned ?? false

    // Dismiss listeners for pinned tooltip
    useEffect(() => {
        if (!isPinned) {
            return
        }

        const handleClickOutside = (e: MouseEvent): void => {
            const wrapper = wrapperRef.current
            if (wrapper && !wrapper.contains(e.target as Node)) {
                clearTooltip()
            }
        }

        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'Escape') {
                clearTooltip()
            }
        }

        const handleScroll = (e: Event): void => {
            // Ignore scrolls that originate inside the tooltip itself — users
            // should be able to scroll long pinned content without dismissing it.
            const target = e.target as Element | null
            if (target && typeof target.closest === 'function' && target.closest('[data-hog-charts-tooltip]')) {
                return
            }
            clearTooltip()
        }

        // Delay click listener so the pinning click doesn't immediately unpin
        const timer = setTimeout(() => {
            document.addEventListener('click', handleClickOutside, { passive: true })
        }, 0)
        document.addEventListener('keydown', handleKeyDown, { passive: true })
        window.addEventListener('scroll', handleScroll, { passive: true, capture: true })

        return () => {
            clearTimeout(timer)
            document.removeEventListener('click', handleClickOutside)
            document.removeEventListener('keydown', handleKeyDown)
            window.removeEventListener('scroll', handleScroll, true)
        }
    }, [isPinned, wrapperRef, clearTooltip])

    const onMouseMove = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!scales || !dimensions || isPinned) {
                return
            }

            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const mouseY = e.clientY - rect.top

            if (!isInPlotArea(mouseX, mouseY, dimensions)) {
                clearTooltip()
                return
            }

            const index = findNearestIndex(mouseX, labels, scales.x)
            setHoverIndex(index)

            if (index >= 0 && showTooltip) {
                const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
                const ctx = buildTooltipContext(index, series, labels, scales.x, scales.y, canvasBounds, resolveValue)
                if (ctx) {
                    setTooltipCtx(ctx)
                }
            }
        },
        [scales, dimensions, labels, series, showTooltip, resolveValue, canvasRef, isPinned, clearTooltip]
    )

    const onMouseLeave = useCallback(() => {
        if (isPinned) {
            return
        }
        clearTooltip()
    }, [isPinned, clearTooltip])

    const onClick = useCallback(() => {
        const currentIndex = hoverIndexRef.current
        if (currentIndex < 0) {
            return
        }

        if (isPinned) {
            clearTooltip()
            return
        }

        // Pin the tooltip if pinnable and there are multiple series
        if (pinnable && tooltipCtx && tooltipCtx.seriesData.length > 1) {
            setTooltipCtx({ ...tooltipCtx, isPinned: true, onUnpin: unpin })
            return
        }

        if (onPointClick) {
            const clickData = buildPointClickData(currentIndex, series, labels, resolveValue)
            if (clickData) {
                onPointClick(clickData)
            }
        }
    }, [onPointClick, series, labels, resolveValue, pinnable, tooltipCtx, isPinned, clearTooltip, unpin, hoverIndexRef])

    const handlers = useMemo(() => ({ onMouseMove, onMouseLeave, onClick }), [onMouseMove, onMouseLeave, onClick])

    return { hoverIndex, tooltipCtx, handlers }
}
