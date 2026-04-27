import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { buildPointClickData, buildTooltipContext, findNearestIndex, isInPlotArea } from '../interaction'
import type { ChartDimensions, ChartScales, PointClickData, ResolveValueFn, Series, TooltipContext } from '../types'

const defaultResolveValue: ResolveValueFn = (series, dataIndex) => series.data[dataIndex] ?? 0

interface UseChartInteractionOptions<Meta> {
    scales: ChartScales | null
    dimensions: ChartDimensions | null
    labels: string[]
    series: Series<Meta>[]
    canvasRef: React.RefObject<HTMLCanvasElement>
    wrapperRef: React.RefObject<HTMLDivElement>
    showTooltip: boolean
    pinnable: boolean
    onPointClick?: (data: PointClickData<Meta>) => void
    resolveValue?: ResolveValueFn
}

interface UseChartInteractionResult<Meta> {
    hoverIndex: number
    tooltipCtx: TooltipContext<Meta> | null
    handlers: {
        onMouseMove: (e: React.MouseEvent<HTMLDivElement>) => void
        onMouseLeave: () => void
        onClick: () => void
    }
}

export function useChartInteraction<Meta = unknown>({
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
}: UseChartInteractionOptions<Meta>): UseChartInteractionResult<Meta> {
    const [hoverIndex, setHoverIndex] = useState<number>(-1)
    const [tooltipCtx, setTooltipCtx] = useState<TooltipContext<Meta> | null>(null)
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

    // Rebuild or clear the pinned tooltip when its underlying inputs change.
    // Without this, the pin keeps stale values at stale pixel positions after the
    // parent updates series/labels/scales/dimensions. resolveValue is read live via a
    // ref so each render's new closure doesn't trigger a rebuild.
    const resolveValueRef = useRef(resolveValue)
    resolveValueRef.current = resolveValue
    useEffect(() => {
        if (!isPinned || !scales || !dimensions) {
            return
        }
        setTooltipCtx((prev) => {
            if (!prev || !prev.isPinned) {
                return prev
            }
            if (prev.dataIndex >= labels.length) {
                return null
            }
            const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
            const fresh = buildTooltipContext(
                prev.dataIndex,
                series,
                labels,
                scales.x,
                scales.y,
                canvasBounds,
                resolveValueRef.current,
                scales.yAxes
            )
            return fresh ? { ...fresh, isPinned: true, onUnpin: unpin } : null
        })
        // Omitted on purpose:
        //   - isPinned / tooltipCtx: would feedback-loop with setTooltipCtx
        //   - unpin / canvasRef: stable for the lifetime of the hook (useCallback([])/useRef)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [series, labels, scales, dimensions])

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
            // Ignore scrolls that originate inside the tooltip itself or inside
            // the chart wrapper — users should be able to scroll long pinned
            // content (or a nested legend) without dismissing the tooltip.
            const target = e.target
            if (target instanceof Element) {
                if (target.closest('[data-hog-charts-tooltip]')) {
                    return
                }
                if (wrapperRef.current?.contains(target)) {
                    return
                }
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
                // Always propagate the result (including null) so tooltipCtx stays in sync with hoverIndex.
                setTooltipCtx(
                    buildTooltipContext(
                        index,
                        series,
                        labels,
                        scales.x,
                        scales.y,
                        canvasBounds,
                        resolveValue,
                        scales.yAxes
                    )
                )
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

        // Pin the tooltip if pinnable and there are multiple series — first click pins,
        // a follow-up click on a tooltip row drills into a specific series via the
        // consumer's own row handler. With a single series there's nothing to pin, so
        // onPointClick fires immediately instead.
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
