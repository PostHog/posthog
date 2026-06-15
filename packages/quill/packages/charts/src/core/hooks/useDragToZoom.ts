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
    onDragActivate,
}: UseDragToZoomOptions): UseDragToZoomResult {
    const [dragRect, setDragRect] = useState<DragRect | null>(null)
    const dragOriginRef = useRef<{ x: number; y: number; active: boolean } | null>(null)
    const dragJustCompletedRef = useRef(false)
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
                    const ls = labelsRef.current
                    onDateRangeZoomRef.current({
                        startLabel: ls[range.startIndex],
                        endLabel: ls[range.endIndex],
                        startIndex: range.startIndex,
                        endIndex: range.endIndex,
                    })
                }
                dragJustCompletedRef.current = true
                setTimeout(() => {
                    dragJustCompletedRef.current = false
                }, 0)
            }
            dragOriginRef.current = null
            setDragRect(null)
        },
        [labelPositionsRef, labelsRef, onDateRangeZoomRef]
    )

    // Global mouseup catches gestures that end outside the chart wrapper.
    useEffect(() => {
        if (!onDateRangeZoom) {
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
    }, [onDateRangeZoom, wrapperRef, completeDrag])

    const onMouseDown = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!onDateRangeZoom || !scales || !dimensions || e.button !== 0) {
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
        [onDateRangeZoom, scales, dimensions]
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
