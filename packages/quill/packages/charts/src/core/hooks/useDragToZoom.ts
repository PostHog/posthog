import React, { useCallback, useEffect, useRef, useState } from 'react'

import { dragRectToLabelRange, isInPlotArea } from '../interaction'
import type { LabelPosition } from '../interaction'
import type { ChartDimensions, ChartScales, DateRangeZoomData, DragRect } from '../types'
import { useLatest } from './useLatest'

// Movement (px) required before a mousedown becomes a drag rather than a click.
const DRAG_THRESHOLD_PX = 4

interface UseDragToZoomOptions {
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    scales: ChartScales | null
    dimensions: ChartDimensions | null
    labels: string[]
    labelPositions: LabelPosition[]
    wrapperRef: React.RefObject<HTMLDivElement>
    /** Drag-to-zoom only operates on a horizontal x-axis; it's disabled when the chart's
     *  interaction axis is vertical. */
    interactionAxis?: 'x' | 'y'
    /** Fired once when a drag crosses the activation threshold (used to dismiss the hover tooltip). */
    onDragActivate: () => void
}

interface UseDragToZoomResult {
    /** Live pixel range of the in-progress selection, or null when no drag is active. */
    dragRect: DragRect | null
    onMouseDown: (e: React.MouseEvent<HTMLDivElement>) => void
    /** Feed each mousemove's plot-relative coords. Returns true when the move was consumed by an
     *  active drag — the caller should then skip its own hover handling for this event. */
    handleMouseMove: (mouseX: number, mouseY: number) => boolean
    /** Returns true when the click immediately follows a completed drag and should be swallowed. */
    shouldSwallowClick: () => boolean
}

/** Drag-to-zoom gesture for the x-axis, factored out of `useChartInteraction`. Tracks a horizontal
 *  selection from mousedown to mouseup and emits the spanned label range via `onDateRangeZoom`. */
export function useDragToZoom({
    onDateRangeZoom,
    scales,
    dimensions,
    labels,
    labelPositions,
    wrapperRef,
    interactionAxis = 'x',
    onDragActivate,
}: UseDragToZoomOptions): UseDragToZoomResult {
    const [dragRect, setDragRect] = useState<DragRect | null>(null)
    const dragOriginRef = useRef<{ x: number; y: number; active: boolean } | null>(null)
    const dragJustCompletedRef = useRef(false)
    const swallowResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const labelsRef = useLatest(labels)
    const labelPositionsRef = useLatest(labelPositions)
    const onDateRangeZoomRef = useLatest(onDateRangeZoom)
    const onDragActivateRef = useLatest(onDragActivate)

    const completeDrag = useCallback(
        (mouseX: number) => {
            const origin = dragOriginRef.current
            if (!origin) {
                return
            }
            if (origin.active) {
                const range = dragRectToLabelRange({ x0: origin.x, x1: mouseX }, labelPositionsRef.current)
                if (range && onDateRangeZoomRef.current) {
                    const currentLabels = labelsRef.current
                    onDateRangeZoomRef.current({
                        startLabel: currentLabels[range.startIndex],
                        endLabel: currentLabels[range.endIndex],
                        startIndex: range.startIndex,
                        endIndex: range.endIndex,
                    })
                }
                // Swallow the trailing `click` that the browser fires after the gesture's mouseup.
                // shouldSwallowClick() clears this synchronously on that click; the timer is the
                // fallback for when no click follows (drag released off-target), cleared on unmount.
                dragJustCompletedRef.current = true
                if (swallowResetTimerRef.current) {
                    clearTimeout(swallowResetTimerRef.current)
                }
                swallowResetTimerRef.current = setTimeout(() => {
                    dragJustCompletedRef.current = false
                    swallowResetTimerRef.current = null
                }, 0)
            }
            dragOriginRef.current = null
            setDragRect(null)
        },
        [labelPositionsRef, labelsRef, onDateRangeZoomRef]
    )

    // Global mouseup catches gestures that end outside the chart wrapper. Gate on a stable
    // boolean rather than the `onDateRangeZoom` identity so an inline-arrow prop (the common
    // case) doesn't re-subscribe this window listener on every parent render.
    const zoomEnabled = !!onDateRangeZoom && interactionAxis === 'x'
    useEffect(() => {
        if (!zoomEnabled) {
            return
        }
        const handler = (e: MouseEvent): void => {
            if (!dragOriginRef.current) {
                return
            }
            const wrapper = wrapperRef.current
            const mouseX = wrapper ? e.clientX - wrapper.getBoundingClientRect().left : 0
            completeDrag(mouseX)
        }
        window.addEventListener('mouseup', handler)
        return () => window.removeEventListener('mouseup', handler)
    }, [zoomEnabled, wrapperRef, completeDrag])

    useEffect(
        () => () => {
            if (swallowResetTimerRef.current) {
                clearTimeout(swallowResetTimerRef.current)
            }
        },
        []
    )

    const onMouseDown = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!zoomEnabled || !scales || !dimensions || e.button !== 0) {
                return
            }
            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const mouseY = e.clientY - rect.top
            if (!isInPlotArea(mouseX, mouseY, dimensions)) {
                return
            }
            dragOriginRef.current = { x: mouseX, y: mouseY, active: false }
        },
        [zoomEnabled, scales, dimensions]
    )

    const handleMouseMove = useCallback(
        (mouseX: number, mouseY: number): boolean => {
            const origin = dragOriginRef.current
            if (!origin) {
                return false
            }
            if (!origin.active && Math.hypot(mouseX - origin.x, mouseY - origin.y) >= DRAG_THRESHOLD_PX) {
                origin.active = true
                onDragActivateRef.current()
            }
            if (origin.active) {
                setDragRect({ x0: origin.x, x1: mouseX })
                return true
            }
            return false
        },
        [onDragActivateRef]
    )

    const shouldSwallowClick = useCallback((): boolean => {
        if (dragJustCompletedRef.current) {
            dragJustCompletedRef.current = false
            return true
        }
        return false
    }, [])

    return { dragRect, onMouseDown, handleMouseMove, shouldSwallowClick }
}
