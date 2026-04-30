import React, { useCallback, useEffect, useMemo, useState } from 'react'

import {
    buildLabelPositions,
    buildPointClickData,
    buildTooltipContext,
    findNearestIndexFromPositions,
    isInPlotArea,
} from '../interaction'
import type {
    ChartDimensions,
    ChartScales,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    TooltipContext,
} from '../types'
import { useLatest } from './useLatest'

const defaultResolveValue: ResolveValueFn = (series, dataIndex) => series.data[dataIndex] ?? 0

function isTooltipContextEquivalent<Meta>(a: TooltipContext<Meta>, b: TooltipContext<Meta>): boolean {
    if (a.dataIndex !== b.dataIndex || a.label !== b.label) {
        return false
    }
    if (a.position.x !== b.position.x || a.position.y !== b.position.y) {
        return false
    }
    if (a.seriesData.length !== b.seriesData.length) {
        return false
    }
    for (let i = 0; i < a.seriesData.length; i++) {
        const ai = a.seriesData[i]
        const bi = b.seriesData[i]
        // Compare series by stable `key` rather than identity: the parent rebuilds
        // `coloredSeries` (and so each entry's `series` reference) on every render, so
        // an identity check would defeat the equivalence bail. `label` is also compared
        // because it's user-visible in the tooltip and can change while the key stays.
        if (
            ai.value !== bi.value ||
            ai.color !== bi.color ||
            ai.series.key !== bi.series.key ||
            ai.series.label !== bi.series.label
        ) {
            return false
        }
    }
    return true
}

interface UseChartInteractionOptions<Meta> {
    scales: ChartScales | null
    dimensions: ChartDimensions | null
    labels: string[]
    series: ResolvedSeries<Meta>[]
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
    // Read by onClick to decide pin/unpin/passthrough. Event handlers fire after the
    // most recent commit, so an effect-deferred ref is correct here.
    const hoverIndexRef = useLatest(hoverIndex)

    const clearTooltip = useCallback(() => {
        setHoverIndex(-1)
        setTooltipCtx(null)
    }, [])

    const unpin = useCallback(() => {
        setTooltipCtx((prev) => (prev?.isPinned ? null : prev))
    }, [])

    const isPinned = tooltipCtx?.isPinned ?? false

    // Precompute the (x, index) lookup table once per (labels, scales.x) change.
    const labelPositions = useMemo(() => (scales ? buildLabelPositions(labels, scales.x) : []), [labels, scales])

    // Rebuild or clear the pinned tooltip when its underlying inputs change.
    // Without this, the pin keeps stale values at stale pixel positions after the
    // parent updates series/labels/scales/dimensions. resolveValue is read live via
    // a ref so unmemoized closures don't trigger a rebuild every render — see the
    // contract on `ChartProps.resolveValue`: any external toggle that changes the
    // resolver's output must also update series or scales.
    const resolveValueRef = useLatest(resolveValue)
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
            if (!fresh) {
                return null
            }
            // Bail when the rebuilt context is value-equal to prev. Avoids identity churn
            // re-rendering the tooltip overlay when the parent rerenders for unrelated
            // reasons (e.g. dashboard-level state) while the pin is held.
            if (isTooltipContextEquivalent(prev, fresh)) {
                return prev
            }
            return { ...fresh, isPinned: true, onUnpin: unpin }
        })
        // Omitted on purpose:
        //   - isPinned / tooltipCtx: would feedback-loop with setTooltipCtx
        //   - unpin / canvasRef: stable for the lifetime of the hook (useCallback([])/useRef)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [series, labels, scales, dimensions])

    // Dismiss the tooltip on scroll — pinned or not — since the anchor moves
    // with the page and a stale tooltip is worse than no tooltip.
    const tooltipShown = tooltipCtx !== null
    useEffect(() => {
        if (!tooltipShown) {
            return
        }
        const handleScroll = (e: Event): void => {
            // Allow scrolling inside the tooltip itself (long pinned content)
            // or the chart wrapper (a nested legend) without dismissing.
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
        window.addEventListener('scroll', handleScroll, { passive: true, capture: true })
        return () => {
            window.removeEventListener('scroll', handleScroll, true)
        }
    }, [tooltipShown, wrapperRef, clearTooltip])

    // Dismiss listeners for pinned tooltip
    useEffect(() => {
        if (!isPinned) {
            return
        }

        const handleClickOutside = (e: MouseEvent): void => {
            const target = e.target
            if (target instanceof Element && target.closest('[data-hog-charts-tooltip]')) {
                return
            }
            const wrapper = wrapperRef.current
            if (wrapper && !wrapper.contains(target as Node)) {
                clearTooltip()
            }
        }

        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'Escape') {
                clearTooltip()
            }
        }

        // Delay click listener so the pinning click doesn't immediately unpin
        const timer = setTimeout(() => {
            document.addEventListener('click', handleClickOutside, { passive: true })
        }, 0)
        document.addEventListener('keydown', handleKeyDown, { passive: true })

        return () => {
            clearTimeout(timer)
            document.removeEventListener('click', handleClickOutside)
            document.removeEventListener('keydown', handleKeyDown)
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

            const index = findNearestIndexFromPositions(mouseX, labelPositions)
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
        [
            scales,
            dimensions,
            labels,
            series,
            showTooltip,
            resolveValue,
            canvasRef,
            isPinned,
            clearTooltip,
            labelPositions,
        ]
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
