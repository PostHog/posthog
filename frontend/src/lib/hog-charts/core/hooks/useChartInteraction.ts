import React, { useCallback, useMemo } from 'react'

import {
    buildLabelPositions,
    buildPointClickData,
    buildTooltipContext,
    findNearestIndexFromPositions,
    isInPlotArea,
} from '../interaction'
import { defaultResolveValue } from '../types'
import type {
    ChartDimensions,
    ChartScales,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    TooltipContext,
} from '../types'
import { useLatest } from './useLatest'
import { useTooltipLifecycle } from './useTooltipLifecycle'

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
    /** Value used to *anchor* the tooltip per series. Defaults to `resolveValue`. Stacked
     *  charts pass the stacked-top resolver so the anchor lands at the visual top of each
     *  segment while each tooltip row still shows its own value via `resolveValue`. */
    resolvePositionValue?: ResolveValueFn
    interactionAxis?: 'x' | 'y'
    labelToCoord?: (label: string) => number | undefined
}

interface UseChartInteractionResult<Meta> {
    hoverIndex: number
    hoverPosition: { x: number; y: number } | null
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
    resolvePositionValue,
    interactionAxis = 'x',
    labelToCoord,
}: UseChartInteractionOptions<Meta>): UseChartInteractionResult<Meta> {
    // Falls back to the value resolver when the chart doesn't distinguish position from
    // value (i.e. non-stacked charts, where the two are identical).
    const effectivePositionResolve = resolvePositionValue ?? resolveValue

    // resolveValue / effectivePositionResolve are read live in the pinned-rebuild path so an
    // unmemoized closure on either doesn't trigger a rebuild every render — see the contract
    // on `ChartProps.resolveValue`.
    const resolveValueRef = useLatest(resolveValue)
    const effectivePositionResolveRef = useLatest(effectivePositionResolve)

    const rebuildPinnedCtx = useCallback(
        (prev: TooltipContext<Meta>): TooltipContext<Meta> | null => {
            if (!scales || !dimensions) {
                return prev
            }
            if (prev.dataIndex >= labels.length) {
                return null
            }
            const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
            return buildTooltipContext(
                prev.dataIndex,
                series,
                labels,
                labelToCoord ?? scales.x,
                scales.y,
                canvasBounds,
                resolveValueRef.current,
                scales.yAxes,
                interactionAxis,
                prev.hoverPosition,
                effectivePositionResolveRef.current,
                scales.extent?.(labels[prev.dataIndex])
            )
        },
        // resolveValueRef / effectivePositionResolveRef are stable
        [
            scales,
            dimensions,
            labels,
            series,
            canvasRef,
            labelToCoord,
            interactionAxis,
            resolveValueRef,
            effectivePositionResolveRef,
        ]
    )

    const { hoverIndex, hoverPosition, tooltipCtx, setHover, setTooltipCtx, isPinned, clearTooltip, pin } =
        useTooltipLifecycle<Meta>({
            wrapperRef,
            rebuildPinnedCtx,
            rebuildDeps: [series, labels, scales, dimensions],
        })

    // Read by onClick to decide pin/unpin/passthrough. Event handlers fire after the most
    // recent commit, so an effect-deferred ref is correct here.
    const hoverIndexRef = useLatest(hoverIndex)

    // Precompute the (coord, index) lookup table once per (labels, scale) change.
    const labelPositions = useMemo(
        () => (scales ? buildLabelPositions(labels, labelToCoord ?? scales.x) : []),
        [labels, scales, labelToCoord]
    )

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

            const probe = interactionAxis === 'y' ? mouseY : mouseX
            const index = findNearestIndexFromPositions(probe, labelPositions)
            setHover(index, { x: mouseX, y: mouseY })

            if (index >= 0 && showTooltip) {
                const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
                // Always propagate the result (including null) so tooltipCtx stays in sync with hoverIndex.
                setTooltipCtx(
                    buildTooltipContext(
                        index,
                        series,
                        labels,
                        labelToCoord ?? scales.x,
                        scales.y,
                        canvasBounds,
                        resolveValue,
                        scales.yAxes,
                        interactionAxis,
                        { x: mouseX, y: mouseY },
                        effectivePositionResolve,
                        scales.extent?.(labels[index])
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
            effectivePositionResolve,
            canvasRef,
            isPinned,
            clearTooltip,
            labelPositions,
            labelToCoord,
            interactionAxis,
            setHover,
            setTooltipCtx,
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
            pin()
            return
        }

        if (onPointClick) {
            const clickData = buildPointClickData(currentIndex, series, labels, resolveValue)
            if (clickData) {
                onPointClick(clickData)
            }
        }
    }, [onPointClick, series, labels, resolveValue, pinnable, tooltipCtx, isPinned, clearTooltip, pin, hoverIndexRef])

    const handlers = useMemo(() => ({ onMouseMove, onMouseLeave, onClick }), [onMouseMove, onMouseLeave, onClick])

    return { hoverIndex, hoverPosition, tooltipCtx, handlers }
}
