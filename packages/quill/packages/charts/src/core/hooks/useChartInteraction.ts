import React, { useCallback, useMemo, useRef } from 'react'

import { findClosestSeriesKey } from '../../overlays/tooltipUtils'
import {
    buildLabelPositions,
    buildPointClickData,
    buildTooltipContext,
    findNearestIndexFromPositions,
    isInPlotArea,
} from '../interaction'
import { defaultResolveValue } from '../types'
import type {
    AreaSelectData,
    ChartDimensions,
    ChartScales,
    DateRangeZoomData,
    DragRect,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    TooltipContext,
} from '../types'
import { useDragToZoom } from './useDragToZoom'
import { useLatest } from './useLatest'
import { useTooltipLifecycle } from './useTooltipLifecycle'

function originatesInElement(e: React.SyntheticEvent, selector: string): boolean {
    return e.target instanceof Element && !!e.target.closest(selector)
}

/** The tooltip is portaled out of the wrapper's DOM tree, but React portals still bubble
 *  synthetic events through the React tree — so a click or drag that starts inside the pinned
 *  tooltip reaches the wrapper's handlers and would dismiss the pin or start a zoom drag. */
function originatesInTooltip(e: React.SyntheticEvent): boolean {
    return originatesInElement(e, '[data-hog-charts-tooltip]')
}

/** An interactive overlay child (e.g. a clickable exemplar marker) renders inside the same
 *  wrapper this hook's mousemove handler is bound to, so every hover over it still bubbles here.
 *  Without this guard the chart's own nearest-point tooltip fights the overlay child's tooltip
 *  for the cursor. An overlay opts out of chart hover tracking by marking its interactive root
 *  with this attribute. */
function originatesInInteractiveOverlay(e: React.SyntheticEvent): boolean {
    return originatesInElement(e, '[data-hog-charts-interactive-overlay]')
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
    /** See `TooltipConfig.resolveClickToNearestSeries`. */
    resolveClickToNearestSeries?: boolean
    onPointClick?: (data: PointClickData<Meta>) => void
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    /** 2D brush — see `ChartProps.onAreaSelect`. Receives the committed `scales` so chart-type
     *  adapters can map the y pixel range onto their own bands. */
    onAreaSelect?: (data: AreaSelectData, scales: ChartScales) => void
    resolveValue?: ResolveValueFn
    /** Value used to *anchor* the tooltip per series. Defaults to `resolveValue`. Stacked
     *  charts pass the stacked-top resolver so the anchor lands at the visual top of each
     *  segment while each tooltip row still shows its own value via `resolveValue`. */
    resolvePositionValue?: ResolveValueFn
    /** Resolves the stacked bottom value per series — passed to buildTooltipContext so yPixel
     *  is set to the segment midpoint, making closest-series detection match the visual boundary. */
    resolveBottomValue?: ResolveValueFn
    interactionAxis?: 'x' | 'y'
    labelToCoord?: (label: string) => number | undefined
    /** Chart-type seam: rewrite the click payload (e.g. resolve the stacked segment under the
     *  cursor) before it reaches `onPointClick`, using the committed `scales` from this render.
     *  Chart-type adapters provide this; consumers do not. */
    wrapClickData?: (data: PointClickData<Meta>, scales: ChartScales) => PointClickData<Meta>
    /** Chart-type seam: given the nearest band index and the cursor, return the effective hover index —
     *  or -1 to treat the position as a dead zone (no tooltip, pointer cursor, highlight, or click).
     *  BarChart uses it to make a capped track's blank volume gap inert. Adapters provide this. */
    resolveHoverIndex?: (index: number, cursor: { x: number; y: number }, scales: ChartScales) => number
}

/** Resolves a click on a pinnable multi-series chart to whichever series is nearest the cursor,
 *  reusing the already-computed tooltip row values/positions rather than re-deriving them —
 *  `tooltipCtx.seriesData` reflects each series' own tooltip-visibility and value formatting,
 *  which a fresh lookup via `buildPointClickData` would not. Returns `null` when no series is
 *  closest (e.g. an empty tooltip). */
function resolveNearestSeriesClickData<Meta>(
    dataIndex: number,
    series: ResolvedSeries<Meta>[],
    labels: string[],
    tooltipCtx: TooltipContext<Meta>,
    interactionAxis: 'x' | 'y',
    cursor: { x: number; y: number }
): PointClickData<Meta> | null {
    const cursorValueCoord = interactionAxis === 'y' ? cursor.x : cursor.y
    const closestKey = findClosestSeriesKey(tooltipCtx.seriesData, cursorValueCoord)
    const closest = closestKey ? tooltipCtx.seriesData.find((d) => d.series.key === closestKey) : undefined
    if (!closest) {
        return null
    }
    return {
        seriesIndex: series.findIndex((s) => s.key === closest.series.key),
        dataIndex,
        series: closest.series,
        value: closest.value,
        label: labels[dataIndex],
        crossSeriesData: tooltipCtx.seriesData.map((d) => ({ series: d.series, value: d.value })),
        cursor,
    }
}

interface UseChartInteractionResult<Meta> {
    hoverIndex: number
    hoverPosition: { x: number; y: number } | null
    tooltipCtx: TooltipContext<Meta> | null
    dragRect: DragRect | null
    handlers: {
        onMouseDown: (e: React.MouseEvent<HTMLDivElement>) => void
        onMouseMove: (e: React.MouseEvent<HTMLDivElement>) => void
        onMouseLeave: () => void
        onClick: (e: React.MouseEvent<HTMLDivElement>) => void
        onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void
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
    resolveClickToNearestSeries = false,
    onPointClick,
    onDateRangeZoom,
    onAreaSelect,
    resolveValue = defaultResolveValue,
    resolvePositionValue,
    resolveBottomValue,
    interactionAxis = 'x',
    labelToCoord,
    wrapClickData,
    resolveHoverIndex,
}: UseChartInteractionOptions<Meta>): UseChartInteractionResult<Meta> {
    // Falls back to the value resolver when the chart doesn't distinguish position from
    // value (i.e. non-stacked charts, where the two are identical).
    const effectivePositionResolve = resolvePositionValue ?? resolveValue

    // resolveValue / effectivePositionResolve / resolveBottomValue are read live in the
    // pinned-rebuild path so an unmemoized closure on any of them doesn't trigger a rebuild
    // every render — see the contract on `ChartProps.resolveValue`.
    const resolveValueRef = useLatest(resolveValue)
    const effectivePositionResolveRef = useLatest(effectivePositionResolve)
    const resolveBottomValueRef = useLatest(resolveBottomValue)

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
                resolveBottomValueRef.current,
                scales.extent?.(labels[prev.dataIndex]),
                prev.hoverPosition ? scales.bandSlotAtCursor?.(labels[prev.dataIndex], prev.hoverPosition) : undefined
            )
        },
        // resolveValueRef / effectivePositionResolveRef / resolveBottomValueRef are stable refs
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
            resolveBottomValueRef,
        ]
    )

    const { hoverIndex, hoverPosition, tooltipCtx, setHover, setTooltipCtx, isPinned, clearTooltip, pin, unpin } =
        useTooltipLifecycle<Meta>({
            wrapperRef,
            rebuildPinnedCtx,
            rebuildDeps: [series, labels, scales, dimensions],
        })

    // Read by onClick to decide pin/unpin/passthrough. Event handlers fire after the most
    // recent commit, so an effect-deferred ref is correct here.
    const hoverIndexRef = useLatest(hoverIndex)
    const hoverPositionRef = useLatest(hoverPosition)

    // Precompute the (coord, index) lookup table once per (labels, scale) change.
    const labelPositions = useMemo(
        () => (scales ? buildLabelPositions(labels, labelToCoord ?? scales.x) : []),
        [labels, scales, labelToCoord]
    )

    // Bind the committed scales into the 2D-brush callback so chart-type adapters can map the
    // y pixel range onto their own bands (the core has no y-band concept).
    const onAreaSelectWithScales = useMemo(
        () => (onAreaSelect && scales ? (data: AreaSelectData): void => onAreaSelect(data, scales) : undefined),
        [onAreaSelect, scales]
    )

    const {
        dragRect,
        onMouseDown,
        handleMouseMove: handleDragMouseMove,
        shouldSwallowClick,
    } = useDragToZoom({
        onDateRangeZoom,
        onAreaSelect: onAreaSelectWithScales,
        scales,
        dimensions,
        labels,
        labelPositions,
        wrapperRef,
        interactionAxis,
        onDragActivate: clearTooltip,
    })

    // Cursor → data-index hit test, shared by mousemove hover and touch taps.
    const resolveIndexAt = useCallback(
        (x: number, y: number): number => {
            if (!scales || !dimensions || !isInPlotArea(x, y, dimensions)) {
                return -1
            }
            const probe = interactionAxis === 'y' ? y : x
            const nearestIndex = findNearestIndexFromPositions(probe, labelPositions)
            // Chart-type dead-zone veto (e.g. a funnel compare bar's blank volume gap): treat as
            // no-hover so tooltip, pointer cursor, highlight, and click are all suppressed there.
            return nearestIndex >= 0 && resolveHoverIndex
                ? resolveHoverIndex(nearestIndex, { x, y }, scales)
                : nearestIndex
        },
        [scales, dimensions, interactionAxis, labelPositions, resolveHoverIndex]
    )

    const buildCtxAt = useCallback(
        (index: number, position: { x: number; y: number }): TooltipContext<Meta> | null => {
            if (!scales) {
                return null
            }
            const canvasBounds = canvasRef.current?.getBoundingClientRect() ?? new DOMRect()
            return buildTooltipContext(
                index,
                series,
                labels,
                labelToCoord ?? scales.x,
                scales.y,
                canvasBounds,
                resolveValue,
                scales.yAxes,
                interactionAxis,
                position,
                effectivePositionResolve,
                resolveBottomValue,
                scales.extent?.(labels[index]),
                scales.bandSlotAtCursor?.(labels[index], position)
            )
        },
        [
            scales,
            series,
            labels,
            labelToCoord,
            canvasRef,
            resolveValue,
            interactionAxis,
            effectivePositionResolve,
            resolveBottomValue,
        ]
    )

    const onMouseMove = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!scales || !dimensions) {
                return
            }

            if (originatesInInteractiveOverlay(e)) {
                // Matches onMouseLeave. A pinned tooltip stays until explicitly unpinned, so
                // moving onto an overlay marker must not clear it out from under the user.
                if (!isPinned) {
                    clearTooltip()
                }
                return
            }

            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const mouseY = e.clientY - rect.top

            // An active drag-to-zoom owns the gesture — skip hover handling.
            if (handleDragMouseMove(mouseX, mouseY)) {
                return
            }

            if (isPinned) {
                return
            }

            const index = resolveIndexAt(mouseX, mouseY)
            if (index < 0) {
                clearTooltip()
                return
            }
            setHover(index, { x: mouseX, y: mouseY })

            if (showTooltip) {
                // Always propagate the result (including null) so tooltipCtx stays in sync with hoverIndex.
                setTooltipCtx(buildCtxAt(index, { x: mouseX, y: mouseY }))
            }
        },
        [
            scales,
            dimensions,
            showTooltip,
            isPinned,
            clearTooltip,
            handleDragMouseMove,
            setHover,
            setTooltipCtx,
            resolveIndexAt,
            buildCtxAt,
        ]
    )

    const onMouseLeave = useCallback(() => {
        if (isPinned) {
            return
        }
        clearTooltip()
    }, [isPinned, clearTooltip])

    // Touch support state. Touch devices fire no mousemove before a tap, so hover state is
    // absent (or stale) when the tap's click arrives; the click handler must resolve the tapped
    // point itself. `lastPointerTypeRef` tells it whether the click came from a touch, and
    // `tapDownTooltipIndexRef` records which point's tooltip was showing when the gesture
    // started. Both are captured at pointerdown because a tap's compatibility mouse events
    // (mouseover/mousemove/mousedown) fire after pointerup, which means by click time the
    // tooltip state may already reflect this very tap.
    const tooltipCtxRef = useLatest(tooltipCtx)
    const lastPointerTypeRef = useRef<string>('mouse')
    const tapDownTooltipIndexRef = useRef<number>(-1)

    const onPointerDown = useCallback(
        (e: React.PointerEvent<HTMLDivElement>) => {
            lastPointerTypeRef.current = e.pointerType
            tapDownTooltipIndexRef.current = tooltipCtxRef.current?.dataIndex ?? -1
        },
        [tooltipCtxRef]
    )

    const onClick = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (originatesInTooltip(e)) {
                return
            }
            // A click that closes out a drag-to-zoom gesture must not also pin/unpin or fire onPointClick.
            if (shouldSwallowClick()) {
                return
            }

            let currentIndex = hoverIndexRef.current
            let clickPosition = hoverPositionRef.current

            if (lastPointerTypeRef.current === 'touch') {
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
                const position = { x: e.clientX - rect.left, y: e.clientY - rect.top }
                const index = resolveIndexAt(position.x, position.y)
                if (index < 0) {
                    clearTooltip()
                    return
                }
                // First tap on a point reveals its tooltip instead of acting on it, mirroring the
                // desktop hover-then-click sequence. Pinned when the chart allows it, so the
                // tooltip's rows are tappable and it survives until an outside tap or Escape.
                // Only a tap on the point whose tooltip was already showing when the gesture
                // started falls through to the click action below (dismiss the pin, or drill in).
                if (index !== tapDownTooltipIndexRef.current) {
                    setHover(index, position)
                    if (showTooltip) {
                        const ctx = buildCtxAt(index, position)
                        // Mirror the mouse path: an unambiguous nearest-series tap fires the click
                        // action directly instead of pinning first, so touch users get the same
                        // one-tap drill-in mouse users get on a single click.
                        if (
                            ctx &&
                            pinnable &&
                            resolveClickToNearestSeries &&
                            onPointClick &&
                            ctx.seriesData.length > 1
                        ) {
                            const clickData = resolveNearestSeriesClickData(
                                index,
                                series,
                                labels,
                                ctx,
                                interactionAxis,
                                position
                            )
                            if (clickData) {
                                onPointClick(wrapClickData && scales ? wrapClickData(clickData, scales) : clickData)
                                return
                            }
                        }
                        setTooltipCtx(ctx && pinnable ? { ...ctx, isPinned: true, onUnpin: unpin } : ctx)
                        return
                    }
                }
                currentIndex = index
                clickPosition = position
            }

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
                // Opt-in: a click nearer one series than the others is unambiguous, so resolve it
                // and fire onPointClick directly instead of making the user pin then pick a row.
                if (resolveClickToNearestSeries && onPointClick && clickPosition) {
                    const clickData = resolveNearestSeriesClickData(
                        currentIndex,
                        series,
                        labels,
                        tooltipCtx,
                        interactionAxis,
                        clickPosition
                    )
                    if (clickData) {
                        onPointClick(wrapClickData && scales ? wrapClickData(clickData, scales) : clickData)
                        return
                    }
                }
                pin()
                return
            }

            if (onPointClick) {
                const clickData = buildPointClickData(currentIndex, series, labels, resolveValue, clickPosition)
                if (clickData) {
                    onPointClick(wrapClickData && scales ? wrapClickData(clickData, scales) : clickData)
                }
            }
        },
        [
            onPointClick,
            series,
            labels,
            resolveValue,
            pinnable,
            resolveClickToNearestSeries,
            interactionAxis,
            tooltipCtx,
            isPinned,
            clearTooltip,
            pin,
            unpin,
            shouldSwallowClick,
            hoverIndexRef,
            hoverPositionRef,
            wrapClickData,
            scales,
            showTooltip,
            resolveIndexAt,
            buildCtxAt,
            setHover,
            setTooltipCtx,
        ]
    )

    const guardedMouseDown = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (originatesInTooltip(e) || originatesInInteractiveOverlay(e)) {
                return
            }
            onMouseDown(e)
        },
        [onMouseDown]
    )

    const handlers = useMemo(
        () => ({ onMouseDown: guardedMouseDown, onMouseMove, onMouseLeave, onClick, onPointerDown }),
        [guardedMouseDown, onMouseMove, onMouseLeave, onClick, onPointerDown]
    )

    return { hoverIndex, hoverPosition, tooltipCtx, dragRect, handlers }
}
