import React, { useEffect, useRef, useState } from 'react'

import { DashboardResizeHandles } from 'lib/components/Cards/handles'

export type EditModeEdge = 'n' | 's' | 'w' | 'e' | 'nw' | 'ne' | 'sw' | 'se'

interface EditModeEdgeOverlayProps {
    onEnterEditMode: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
}

const EDGE_ZONE_DATA_ATTR = 'dashboard-edit-mode-from-card-edge'

const edgeOverlayBaseStyle: React.CSSProperties = {
    position: 'absolute',
    zIndex: 5,
    padding: 0,
    margin: 0,
    border: 'none',
    background: 'none',
}

// Top/bottom zones hug the border and reach mostly *into* the tile: the inline "insert tile" overlay owns the
// row gap between tiles (see InsertTileOverlay), so keeping these off the gap avoids fighting it for the same
// pixels. They still win the shared border pixel via a higher z-index. Left/right never touch the insert line.
const TOP_BOTTOM_Z = 7
// Corners sit above edges so a press in the corner resolves to the diagonal handle.
const cornerZoneStyle: React.CSSProperties = { zIndex: TOP_BOTTOM_Z, width: 18, height: 18 }

const zones: { edge: EditModeEdge; style: React.CSSProperties; cursor: React.CSSProperties['cursor'] }[] = [
    // Shallow on top (the card header/menu lives just below) and deeper on the bottom for a comfortable target.
    { edge: 'n', style: { left: 0, right: 0, top: -2, height: 10, zIndex: TOP_BOTTOM_Z }, cursor: 'ns-resize' },
    { edge: 's', style: { left: 0, right: 0, bottom: -2, height: 14, zIndex: TOP_BOTTOM_Z }, cursor: 'ns-resize' },
    { edge: 'w', style: { top: 0, bottom: 0, left: -6, width: 12 }, cursor: 'ew-resize' },
    { edge: 'e', style: { top: 0, bottom: 0, right: -6, width: 12 }, cursor: 'ew-resize' },
    { edge: 'nw', style: { ...cornerZoneStyle, top: -2, left: -2 }, cursor: 'nw-resize' },
    { edge: 'ne', style: { ...cornerZoneStyle, top: -2, right: -2 }, cursor: 'ne-resize' },
    { edge: 'sw', style: { ...cornerZoneStyle, bottom: -2, left: -2 }, cursor: 'sw-resize' },
    { edge: 'se', style: { ...cornerZoneStyle, bottom: -2, right: -2 }, cursor: 'se-resize' },
]

/**
 * Whether the viewport point (x, y) lies on a visible, functional scrollbar of `el`.
 * "Functional" means the content actually overflows on that axis, so a press there would grab the
 * scrollbar rather than hit an empty reserved gutter. Overlay scrollbars (macOS default) occupy no
 * layout space, so `offsetHeight - clientHeight` is 0 and they are never matched.
 */
export function isPointInScrollbarGutter(el: HTMLElement, x: number, y: number): boolean {
    const style = window.getComputedStyle(el)
    const borderTop = parseFloat(style.borderTopWidth) || 0
    const borderBottom = parseFloat(style.borderBottomWidth) || 0
    const borderLeft = parseFloat(style.borderLeftWidth) || 0
    const borderRight = parseFloat(style.borderRightWidth) || 0
    const rect = el.getBoundingClientRect()

    // offsetHeight spans the border box; clientHeight excludes borders and the horizontal scrollbar,
    // so the difference minus borders is the scrollbar's rendered height (0 for overlay scrollbars).
    // The > 1 threshold absorbs the integer rounding of offset/client dimensions.
    const horizontalScrollbarHeight = el.offsetHeight - el.clientHeight - borderTop - borderBottom
    if (horizontalScrollbarHeight > 1 && el.scrollWidth > el.clientWidth) {
        const gutterTop = rect.bottom - borderBottom - horizontalScrollbarHeight
        if (
            y >= gutterTop &&
            y <= rect.bottom - borderBottom &&
            x >= rect.left + borderLeft &&
            x <= rect.right - borderRight
        ) {
            return true
        }
    }

    const verticalScrollbarWidth = el.offsetWidth - el.clientWidth - borderLeft - borderRight
    if (verticalScrollbarWidth > 1 && el.scrollHeight > el.clientHeight) {
        const gutterLeft =
            style.direction === 'rtl' ? rect.left + borderLeft : rect.right - borderRight - verticalScrollbarWidth
        if (
            x >= gutterLeft &&
            x <= gutterLeft + verticalScrollbarWidth &&
            y >= rect.top + borderTop &&
            y <= rect.bottom - borderBottom
        ) {
            return true
        }
    }

    return false
}

/** Whether any element of the card under the viewport point shows a functional scrollbar there. */
function pointIsOverScrollbarInside(container: HTMLElement, x: number, y: number): boolean {
    return document
        .elementsFromPoint(x, y)
        .some(
            (el) =>
                el instanceof HTMLElement &&
                el.dataset.attr !== EDGE_ZONE_DATA_ATTR &&
                container.contains(el) &&
                isPointInScrollbarGutter(el, x, y)
        )
}

export const EditModeEdgeOverlay: React.FC<EditModeEdgeOverlayProps> = ({ onEnterEditMode }) => {
    const [hovering, setHovering] = useState(false)
    // Count entered zones rather than toggling a boolean, so following the border across overlapping
    // edge/corner zones never dips to "not hovering" for a frame and flickers the handles.
    const hoverCount = useRef(0)
    // Zones whose pixels currently sit on top of a scrollbar of the tile's content. They get
    // `pointer-events: none` so presses and wheel events reach the scrollbar natively: a native
    // scrollbar drag only engages when the browser hit-tests the pointer to the scrollable element
    // itself, so an intercept-then-forward approach cannot work. The main case is a table insight
    // whose horizontal scrollbar renders in the card's bottom pixels, exactly under the "s" zone.
    const [scrollbarPassThroughEdges, setScrollbarPassThroughEdges] = useState<ReadonlySet<EditModeEdge>>(new Set())
    const zoneRefs = useRef(new Map<EditModeEdge, HTMLDivElement | null>())

    const releaseHover = (): void => {
        hoverCount.current = Math.max(0, hoverCount.current - 1)
        if (hoverCount.current === 0) {
            setHovering(false)
        }
    }

    const evaluateScrollbarPassThrough = (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge): void => {
        const container = event.currentTarget.parentElement
        if (!container || scrollbarPassThroughEdges.has(edge)) {
            return
        }
        if (pointIsOverScrollbarInside(container, event.clientX, event.clientY)) {
            setScrollbarPassThroughEdges((prev) => new Set(prev).add(edge))
            // The zone's own mouseleave won't fire once it ignores pointer events, so release here.
            releaseHover()
        }
    }

    useEffect(() => {
        if (scrollbarPassThroughEdges.size === 0) {
            return
        }
        // While any zone is letting events through, watch the pointer at the document level and
        // re-enable the zone once the pointer is no longer over the scrollbar beneath it.
        const handleMove = (event: MouseEvent): void => {
            setScrollbarPassThroughEdges((prev) => {
                let next: Set<EditModeEdge> | null = null
                for (const edge of prev) {
                    const zone = zoneRefs.current.get(edge)
                    const container = zone?.parentElement
                    const rect = zone?.getBoundingClientRect()
                    const inZone =
                        !!rect &&
                        event.clientX >= rect.left &&
                        event.clientX <= rect.right &&
                        event.clientY >= rect.top &&
                        event.clientY <= rect.bottom
                    if (!inZone || !container || !pointIsOverScrollbarInside(container, event.clientX, event.clientY)) {
                        next = next ?? new Set(prev)
                        next.delete(edge)
                    }
                }
                return next ?? prev
            })
        }
        document.addEventListener('mousemove', handleMove)
        return () => document.removeEventListener('mousemove', handleMove)
    }, [scrollbarPassThroughEdges])

    const handlePress = (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge): void => {
        // A fast press can land before any mousemove had a chance to hand the zone's pixels over to
        // the scrollbar below. The press is lost either way (it targeted the zone), but it must not
        // throw the user into edit mode when they were aiming at a scrollbar.
        const container = event.currentTarget.parentElement
        if (container && pointIsOverScrollbarInside(container, event.clientX, event.clientY)) {
            return
        }
        // Treat any press (click or drag attempt) as intent to edit
        event.preventDefault()
        event.stopPropagation()
        onEnterEditMode(event, edge)
    }

    return (
        <>
            {hovering && <DashboardResizeHandles />}
            {zones.map(({ edge, style, cursor }) => (
                <div
                    key={edge}
                    ref={(el) => {
                        zoneRefs.current.set(edge, el)
                    }}
                    onMouseDown={(event) => handlePress(event, edge)}
                    onMouseMove={(event) => evaluateScrollbarPassThrough(event, edge)}
                    onMouseEnter={(event) => {
                        hoverCount.current += 1
                        setHovering(true)
                        evaluateScrollbarPassThrough(event, edge)
                    }}
                    onMouseLeave={() => releaseHover()}
                    aria-hidden="true"
                    title="Click to edit layout"
                    data-attr={EDGE_ZONE_DATA_ATTR}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        ...edgeOverlayBaseStyle,
                        ...style,
                        cursor,
                        ...(scrollbarPassThroughEdges.has(edge) ? { pointerEvents: 'none' } : {}),
                    }}
                />
            ))}
        </>
    )
}
